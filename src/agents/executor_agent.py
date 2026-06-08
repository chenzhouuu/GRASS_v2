"""Progress-ledger Executor — faithful port of Magentic-UI v0.1.6
``_orchestrate_step_execution`` / ``_prepare_final_answer`` onto LangGraph.

After a plan is approved in ``mode="plan"``, execution is driven by a per-turn
**progress ledger** instead of the Supervisor react loop. Each turn the model
judges (a) is the current step complete, (b) do we need to replan, (c) what is
the single next instruction and which worker runs it, (d) a running summary.

Realized as two nodes:
- ``ledger_node`` runs ONE ledger turn and routes via ``plan_route``:
  ``dispatch`` (→ named worker), ``loop`` (step completed, re-evaluate the next
  step), ``replan`` (→ Replan → PlanGate re-gate), or ``finalize``.
- ``finalize_node`` synthesizes the user-facing answer (→ END).

Fidelity boundary: ledger schema + loop semantics are ported exactly; the
AutoGen speaker dispatch becomes LangGraph conditional edges (one actor per
turn preserved). Completion that advances the step re-enters the Executor
(``loop``) rather than dispatching a stale instruction — the only deliberate
deviation, made for correctness on LangGraph.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..core.planning import (
    INSTRUCTION_AGENT_FORMAT,
    extract_json_from_string,
    validate_ledger_json,
)

logger = logging.getLogger(__name__)

MAX_TURNS = 20
MAX_REPLANS = 3
MAX_JSON_RETRIES = 3
# Consecutive dispatch turns with no new worker results before forcing a replan
# (a worker that keeps returning the same result can never complete its step).
MAX_STALL_ROUNDS = 2

WORKER_AGENTS = ["Cypher", "Analytics", "Optimization", "Report"]

_TEAM_DESCRIPTION = """\
- Cypher: Neo4j graph queries (retrieval, aggregation, spatial lookups).
- Analytics: Python analysis (pandas/scipy) + Plotly charts.
- Optimization: LP/MILP optimization via PuLP.
- Report: PDF report generation (only after data + analysis are complete)."""

_LEDGER_SCHEMA = """\
Output PURE JSON, parsable as-is, with no surrounding text, matching this schema:

{
    "is_current_step_complete": { "reason": "string", "answer": true_or_false },
    "need_to_replan":           { "reason": "string", "answer": true_or_false },
    "instruction_or_question":  { "answer": "concrete instruction for the worker",
                                   "agent_name": "one of: Cypher, Analytics, Optimization, Report" },
    "progress_summary": "one or two sentence summary of progress so far"
}"""

_FINAL_ANSWER_PROMPT = """\
We worked on the following task:
{task}

The steps above were used to address it. Based on the gathered results, provide a
final response to the user. Reference the plan steps so the user can verify the
answer. Be concise but complete. Use markdown; do NOT include raw JSON, Plotly
specs, or chart configuration — charts and maps are rendered separately."""


class ExecutorAgent:
    """Runs the progress-ledger execution loop over an approved plan."""

    agent_name = "executor"

    def __init__(
        self,
        model,
        max_turns: int = MAX_TURNS,
        max_replans: int = MAX_REPLANS,
        max_json_retries: int = MAX_JSON_RETRIES,
        max_stall_rounds: int = MAX_STALL_ROUNDS,
        allow_replans: bool = True,
    ):
        self.model = model
        self.max_turns = max_turns
        self.max_replans = max_replans
        self.max_json_retries = max_json_retries
        self.max_stall_rounds = max_stall_rounds
        self.allow_replans = allow_replans

    # ── graph nodes ───────────────────────────────────────────────────

    def ledger_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run one progress-ledger turn and decide the next transition."""
        plan = state.get("plan") or {}
        enabled = [
            s for s in plan.get("steps", []) if s.get("enabled", True) is not False
        ]
        idx = state.get("current_step_idx") or 0
        n_rounds = state.get("n_rounds") or 0

        # Termination guards (loop entry).
        if not enabled or idx >= len(enabled) or n_rounds >= self.max_turns:
            if n_rounds >= self.max_turns:
                logger.warning("Executor: max_turns (%d) reached -> finalize", self.max_turns)
            return {"plan_route": "finalize"}

        ledger = self._get_ledger(state, enabled, idx)
        if ledger is None:
            logger.warning("Executor: ledger JSON failed -> finalize")
            return {"plan_route": "finalize", "n_rounds": n_rounds + 1}

        update: dict[str, Any] = {"n_rounds": n_rounds + 1}
        summary = ledger.get("progress_summary", "") or ""
        prior = state.get("information_collected") or ""
        update["information_collected"] = (prior + ("\n- " + summary if summary else "")).strip()

        # Replan (skipped on the first turn — nothing has run yet).
        need = ledger.get("need_to_replan", {})
        if n_rounds > 0 and need.get("answer") and self.allow_replans:
            if (state.get("n_replans") or 0) >= self.max_replans:
                logger.warning("Executor: max_replans reached -> finalize")
                update["plan_route"] = "finalize"
                return update
            logger.info("Executor: need_to_replan -> replan")
            update["plan_route"] = "replan"
            update["replan_feedback"] = need.get("reason", "")
            update["stall_rounds"] = 0
            return update

        # Step completion -> advance; re-evaluate (loop) or finalize. Reset the
        # stall tracker since a new step gets a fresh budget.
        if ledger.get("is_current_step_complete", {}).get("answer"):
            idx += 1
            update["current_step_idx"] = idx
            update["plan_route"] = "finalize" if idx >= len(enabled) else "loop"
            update["stall_rounds"] = 0
            update["last_progress_signature"] = None
            return update

        # Dispatch path — but first guard against a non-progressing loop. If the
        # worker results have not changed since the previous dispatch for several
        # rounds, the step can never complete by re-dispatching; force a replan
        # (or finalize when replans are exhausted) instead of looping to
        # max_turns. This is the backstop the smoke run needed: an LLM optimistic
        # "just fetch it next" never escalates on its own.
        sig = self._progress_signature(state)
        prev_sig = state.get("last_progress_signature")
        stall = state.get("stall_rounds") or 0
        stall = stall + 1 if (n_rounds > 0 and prev_sig is not None and sig == prev_sig) else 0

        if stall >= self.max_stall_rounds:
            replans_left = (state.get("n_replans") or 0) < self.max_replans
            logger.warning(
                "Executor: no new results for %d dispatch rounds on step %d -> %s",
                stall, idx + 1, "replan" if (self.allow_replans and replans_left) else "finalize",
            )
            update["stall_rounds"] = 0
            update["last_progress_signature"] = sig
            if self.allow_replans and replans_left:
                update["plan_route"] = "replan"
                update["replan_feedback"] = (
                    f"Execution stalled on step {idx + 1} "
                    f"('{enabled[idx].get('title', '')}'): the assigned worker returned "
                    "the same result for multiple consecutive rounds without satisfying "
                    "the step. Revise the plan — split this step into distinct "
                    "single-action retrievals, reassign it to a more suitable worker, or "
                    "restate the instruction more concretely."
                )
                return update
            update["plan_route"] = "finalize"
            return update

        # Otherwise dispatch the current step's instruction to the named worker.
        update["current_step_idx"] = idx
        ioq = ledger["instruction_or_question"]
        agent = ioq["agent_name"]
        step = enabled[idx]
        update["next_worker"] = agent
        update["worker_task"] = INSTRUCTION_AGENT_FORMAT.format(
            step_index=idx + 1,
            step_title=step.get("title", ""),
            step_details=step.get("details", ""),
            agent_name=agent,
            instruction=ioq.get("answer", ""),
        )
        update["plan_route"] = "dispatch"
        update["stall_rounds"] = stall
        update["last_progress_signature"] = sig
        return update

    def finalize_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Synthesize the final user-facing answer (port of _prepare_final_answer)."""
        task = (state.get("plan") or {}).get("task") or state.get("user_query", "")
        messages = [
            SystemMessage(
                content="You are GRASS, summarizing the results of an executed plan."
            ),
            HumanMessage(
                content=(
                    _FINAL_ANSWER_PROMPT.format(task=task)
                    + "\n\n## Progress\n"
                    + (state.get("information_collected") or "(none)")
                    + "\n\n## Results\n"
                    + self._results_context(state)
                )
            ),
        ]
        try:
            response = self.model.invoke(messages)
            content = getattr(response, "content", "") or ""
        except Exception as exc:  # noqa: BLE001
            logger.error("Executor finalize failed: %s", exc)
            content = "I completed the plan but could not synthesize a final summary."
        return {
            "next_worker": None,
            "response_markdown": content if isinstance(content, str) else str(content),
            "sender": self.agent_name,
            "messages": [AIMessage(content=content if isinstance(content, str) else str(content),
                                   name=self.agent_name)],
        }

    # ── LLM plumbing ──────────────────────────────────────────────────

    def _get_ledger(self, state: dict, enabled: list[dict], idx: int) -> dict | None:
        messages = self._build_ledger_prompt(state, enabled, idx)
        for attempt in range(self.max_json_retries + 1):
            response = self.model.invoke(messages)
            content = getattr(response, "content", "") or ""
            data = extract_json_from_string(content if isinstance(content, str) else str(content))
            if data is not None and validate_ledger_json(data, WORKER_AGENTS):
                return data
            logger.info("Executor: invalid ledger JSON (attempt %d), retrying", attempt + 1)
            messages = messages + [
                AIMessage(content=content if isinstance(content, str) else str(content)),
                HumanMessage(content="Output ONLY the JSON object matching the schema."),
            ]
        return None

    def _build_ledger_prompt(self, state: dict, enabled: list[dict], idx: int) -> list:
        step = enabled[idx]
        plan_str = state.get("plan_str", "")
        task = (state.get("plan") or {}).get("task") or state.get("user_query", "")
        system = SystemMessage(
            content=(
                "You are the executor for GRASS, a supply chain analytics agent. You "
                "track progress against an approved plan and decide the single next "
                "action.\n\n## Team\n" + _TEAM_DESCRIPTION
            )
        )
        human = HumanMessage(
            content=(
                f"Task:\n{task}\n\n"
                f"Current plan:\n{plan_str}\n\n"
                f"We are at step index {idx} (1-based step {idx + 1}):\n"
                f"  Title: {step.get('title', '')}\n"
                f"  Details: {step.get('details', '')}\n"
                f"  agent_name: {step.get('agent', '')}\n\n"
                f"## Results so far\n{self._results_context(state)}\n\n"
                "Answer, with reasoning:\n"
                "- is_current_step_complete: is the step above done given the results?\n"
                "- need_to_replan: only if stuck/looping or the plan can't address the request.\n"
                "- instruction_or_question: the concrete next instruction and which worker "
                f"(one of {WORKER_AGENTS}) should do it.\n"
                "- progress_summary: one or two sentences.\n\n"
                f"{_LEDGER_SCHEMA}"
            )
        )
        return [system, human]

    @staticmethod
    def _progress_signature(state: dict) -> str:
        """A signature of the worker-produced results, for stall detection.

        Captures everything a worker dispatch can change. Deliberately excludes
        monotonically-growing fields (e.g. ``past_steps`` length, ``n_rounds``)
        so that "no new information" produces an unchanged signature even though
        those counters advance every turn.
        """
        cr = state.get("cypher_results") or []
        parts = [
            f"idx={state.get('current_step_idx') or 0}",
            f"cq={state.get('cypher_query') or ''}",
            f"crows={len(cr)}",
            f"cerr={state.get('cypher_error') or ''}",
            f"an={str(state.get('analysis_results') or '')[:200]}",
            f"aerr={state.get('analysis_error') or ''}",
            f"charts={len(state.get('chart_specs') or [])}",
            f"opt={str(state.get('optimization_solution') or '')[:200]}",
            f"operr={state.get('optimization_error') or ''}",
            f"report={state.get('report_file') or ''}",
        ]
        return "|".join(parts)

    @staticmethod
    def _results_context(state: dict) -> str:
        parts: list[str] = []
        cr = state.get("cypher_results")
        if cr:
            cols = list(cr[0].keys()) if cr else []
            parts.append(f"Cypher: {len(cr)} rows; columns={cols}; sample={str(cr[:2])[:300]}")
        if state.get("cypher_error"):
            parts.append(f"Cypher error: {state['cypher_error']}")
        if state.get("analysis_results"):
            parts.append(f"Analysis: {str(state['analysis_results'])[:300]}")
        if state.get("chart_specs"):
            parts.append(f"Charts: {len(state['chart_specs'])} generated")
        if state.get("optimization_solution"):
            parts.append(f"Optimization: {str(state['optimization_solution'])[:300]}")
        if state.get("optimization_error"):
            parts.append(f"Optimization error: {state['optimization_error']}")
        fb = state.get("worker_feedback")
        if fb:
            parts.append(
                "Feedback: "
                + "; ".join(f"[{f.get('type')}] {f.get('message', '')}" for f in fb[-3:])
            )
        ps = state.get("past_steps")
        if ps:
            parts.append("Past steps: " + "; ".join(f"{t}: {r[:60]}" for t, r in ps[-4:]))
        return "\n".join(parts) if parts else "(no results yet)"
