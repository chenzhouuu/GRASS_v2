"""Planner Agent — co-planning with a human approval gate.

Faithful port of the Magentic-UI v0.1.6 co-planning protocol
(``teams/orchestrator/_orchestrator.py``) onto LangGraph. The single
intentional runtime divergence (documented in the Step-1 plan) is that
the AutoGen "pause for the user-proxy and re-enter on response" mechanism
becomes LangGraph's ``interrupt()`` / ``Command(resume=...)``.

The planning loop is realized as three graph nodes connected by
conditional edges, rather than one node with an internal loop — because a
LangGraph node re-runs from the top on every resume, an internal loop
would re-invoke the drafting LLM on each human round. Splitting the loop
keeps every LLM call committed-to-state exactly once and confines
``interrupt()`` to the cheap ``gate_node``:

    Planner(draft) -> PlanGate(interrupt) --accept--> Supervisor (execute)
                          ^                  |
                          |                  +--reject--> Replan -> PlanGate
                          +---------------------------------------'

Branch semantics (accept / edit-and-accept / reject-and-replan, bounded by
``max_replans``) mirror ``_orchestrate_step_planning`` exactly.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from ..core.planning import (
    Plan,
    HumanInputFormat,
    is_accepted_str,
    extract_json_from_string,
    validate_plan_json,
)
from ..utils.message_history import trim_history
from ..utils.schema_loader import get_schema as load_schema_text

logger = logging.getLogger(__name__)

MAX_REPLANS = 3
MAX_JSON_RETRIES = 3
MAX_HISTORY_MESSAGES = 40

# GRASS team roster injected into the planning prompt.
_TEAM_DESCRIPTION = """\
- Cypher: Queries the Neo4j supply-chain knowledge graph (data retrieval,
  aggregation, path queries, spatial lookups with lat/lon).
- Analytics: Python analysis (pandas, scipy, scikit-learn) AND interactive
  Plotly chart generation (bar, line, scatter, heatmap, Sankey, distributions).
- Optimization: LP/MILP optimization via PuLP (transport cost minimization,
  facility location, inventory/production planning).
- Report: Generates a PDF report (fpdf2). Use only after all data gathering
  and analysis are complete.
- ScenarioRunner: Perturbs a previously established optimization baseline to
  evaluate what-if / sensitivity scenarios (e.g. a facility going offline,
  capacity changes, demand shocks). Always preceded in the same plan by an
  Optimization step that establishes the baseline."""

# Ported from get_orchestrator_plan_prompt_json (non-sentinel branch); the
# free-form ``agent_name`` is constrained to the GRASS roster.
_PLAN_JSON_SCHEMA_INSTRUCTIONS = """\
First consider:
- Can the request be answered directly from the conversation context, without
  querying the graph or running analysis (e.g. a greeting, a clarification, a
  follow-up that restates known results)? If so, answer in the "response" field
  and set "needs_plan" to false.
- Otherwise, devise a plan: a sequence of steps, each assigned to one team member.

Each step has: a "title" (one short sentence), "details" (recap the title in one
sentence, then a newline, then the concrete action — at most ~2 sentences), and
"agent" (exactly one of: Cypher, Analytics, Optimization, Report, ScenarioRunner).

Each step must be a SINGLE concrete action achievable in ONE worker invocation.
A worker runs one query/analysis per dispatch, so do NOT bundle two distinct
retrievals into one step: if the request needs both an aggregate (e.g. per-county
counts) AND a relationship/path extraction (e.g. farm→cooperative→processor links),
make them two separate Cypher steps. Aim for the fewest steps that still keeps each
step atomic. Data must be retrieved (Cypher) before it can be analyzed, optimized,
or reported.

For a WHAT-IF question ("what if X changed", "re-run if a plant goes offline",
"how sensitive is the plan to +-X%"), add a step with "agent": "ScenarioRunner".
A ScenarioRunner step MUST be preceded, in the same plan, by an "Optimization"
step that establishes the baseline it perturbs (and the Cypher step that fetches
that baseline's data). Put the what-if change in the step "details" in plain
language (e.g. "Philadelphia Dairy Processing P0042 limited to 2/3 capacity");
ScenarioRunner converts it into the concrete perturbation.

Output PURE JSON, parsable as-is, with no surrounding text, matching this schema:

{
    "response": "a complete direct answer when needs_plan is false, else empty string",
    "task": "a complete restatement of the user's task",
    "plan_summary": "a one-sentence summary of the plan, else empty string",
    "needs_plan": true_or_false,
    "requires_geo": true_or_false,
    "requires_optimization": true_or_false,
    "steps": [
        {"title": "...", "details": "recap \\n detail", "agent": "Cypher"}
    ]
}"""


class PlannerAgent:
    """Drafts, human-gates, and replans a :class:`Plan`."""

    agent_name = "planner"

    def __init__(
        self,
        model,
        prompt_assembler: Any = None,
        max_replans: int = MAX_REPLANS,
        max_json_retries: int = MAX_JSON_RETRIES,
    ):
        self.model = model
        self.prompt_assembler = prompt_assembler  # unused for now; kept for symmetry
        self.max_replans = max_replans
        self.max_json_retries = max_json_retries

    # ── graph nodes ───────────────────────────────────────────────────

    def draft_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Draft the initial plan. Routes to the gate, or ends (no plan)."""
        data = self._get_plan_json(state, replan=False)

        # Drafting failed entirely — fall back to a direct response.
        if data is None:
            logger.warning("Planner: plan drafting failed after retries")
            return {
                "plan_route": "end",
                "in_planning_mode": False,
                "next_worker": None,
                "response_markdown": (
                    "I wasn't able to draft a plan for that request. "
                    "Could you rephrase or add detail?"
                ),
            }

        # Magentic "Case 1": no plan needed — answer directly.
        if not data.get("needs_plan", True):
            return {
                "plan_route": "end",
                "in_planning_mode": False,
                "next_worker": None,
                "response_markdown": data.get("response") or data.get("plan_summary", ""),
            }

        plan = Plan.from_obj(data)
        if plan is None or len(plan) == 0:
            return {
                "plan_route": "end",
                "in_planning_mode": False,
                "next_worker": None,
                "response_markdown": data.get("response") or "I couldn't form a usable plan.",
            }

        return {
            "plan": plan.model_dump(),
            "plan_str": plan.to_plan_str(),
            "in_planning_mode": True,
            "n_replans": state.get("n_replans") or 0,
            "plan_route": "gate",
            "requires_geo": plan.requires_geo,
            "requires_optimization": plan.requires_optimization,
        }

    def gate_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Pause for human review; apply the accept / edit / reject branches.

        This is the ONLY node that calls ``interrupt()``. On resume the node
        re-runs from here (no LLM work precedes the interrupt), and
        ``interrupt`` returns the value passed to ``Command(resume=...)``.
        """
        plan = state.get("plan") or {}
        raw = interrupt(
            {
                "type": "plan",
                "plan": plan,
                "plan_str": state.get("plan_str", ""),
                "summary": plan.get("summary", ""),
                "message": "Review the plan: accept it, edit the steps, or request changes.",
            }
        )
        human = HumanInputFormat.from_obj(raw)

        update: dict[str, Any] = {}
        # Edits are adopted whether accepted or not (mirrors _orchestrate_step_planning).
        if human.plan is not None:
            edited = human.plan
            # The frontend edit carries only steps; preserve task/summary/flags
            # from the drafted plan so provenance and UI signals survive an
            # edit-and-accept (otherwise the executor's final-answer prompt loses
            # the task restatement and requires_geo/optimization reset to False).
            prior = state.get("plan") or {}
            merged = Plan(
                task=edited.task or prior.get("task"),
                summary=edited.summary or prior.get("summary", ""),
                steps=edited.steps,
                requires_geo=edited.requires_geo or bool(prior.get("requires_geo", False)),
                requires_optimization=(
                    edited.requires_optimization
                    or bool(prior.get("requires_optimization", False))
                ),
            )
            update["plan"] = merged.model_dump()
            update["plan_str"] = merged.to_plan_str()
            update["requires_geo"] = merged.requires_geo
            update["requires_optimization"] = merged.requires_optimization

        if human.accepted or is_accepted_str(human.content):
            logger.info("Planner: plan accepted -> execution")
            update["in_planning_mode"] = False
            update["plan_route"] = "execute"
            update["execution_engine"] = "ledger"
            return update

        # Rejected / change requested.
        n_replans = state.get("n_replans") or 0
        if n_replans >= self.max_replans:
            logger.warning(
                "Planner: max_replans (%d) reached; proceeding with current plan",
                self.max_replans,
            )
            update["in_planning_mode"] = False
            update["plan_route"] = "execute"
            update["execution_engine"] = "ledger"
            return update

        logger.info("Planner: plan rejected -> replan (%d/%d)", n_replans + 1, self.max_replans)
        update["plan_route"] = "replan"
        update["replan_feedback"] = human.content
        return update

    def replan_node(self, state: dict[str, Any]) -> dict[str, Any]:
        """Re-draft the plan after rejection, then return to the gate."""
        n_replans = (state.get("n_replans") or 0) + 1
        data = self._get_plan_json(state, replan=True)

        if data is None or not data.get("needs_plan", True):
            # Keep the previous plan; gate again rather than lose it.
            logger.warning("Planner: replan produced no usable plan; re-gating prior plan")
            return {"n_replans": n_replans, "plan_route": "gate"}

        plan = Plan.from_obj(data)
        if plan is None or len(plan) == 0:
            return {"n_replans": n_replans, "plan_route": "gate"}

        # Mid-execution replan: preserve completed steps (port of _replan's
        # `completed_steps + new_plan.steps`). current_step_idx indexes the
        # ENABLED steps of the prior plan; keep it so execution resumes at the
        # first new step.
        idx = state.get("current_step_idx") or 0
        old = state.get("plan") or {}
        completed: list[dict] = []
        if idx > 0:
            enabled_old = [
                s for s in old.get("steps", []) if s.get("enabled", True) is not False
            ]
            completed = enabled_old[:idx]

        if completed:
            combined = Plan.from_obj({
                "task": plan.task or old.get("task"),
                "plan_summary": plan.summary,
                "requires_geo": plan.requires_geo,
                "requires_optimization": plan.requires_optimization,
                "steps": completed + [s.model_dump() for s in plan.steps],
            }) or plan
        else:
            combined = plan

        return {
            "plan": combined.model_dump(),
            "plan_str": combined.to_plan_str(),
            "n_replans": n_replans,
            "in_planning_mode": True,
            "plan_route": "gate",
            "requires_geo": combined.requires_geo,
            "requires_optimization": combined.requires_optimization,
        }

    # ── LLM plumbing (port of _get_json_response) ─────────────────────

    def _get_plan_json(self, state: dict[str, Any], *, replan: bool) -> dict[str, Any] | None:
        """Call the model for a plan-JSON object, validating with retries."""
        messages = self._build_plan_prompt(state, replan=replan)
        for attempt in range(self.max_json_retries + 1):
            response = self.model.invoke(messages)
            content = getattr(response, "content", "") or ""
            data = extract_json_from_string(content if isinstance(content, str) else str(content))
            if data is not None and validate_plan_json(data):
                return data
            logger.info("Planner: invalid plan JSON (attempt %d), retrying", attempt + 1)
            messages = messages + [
                AIMessage(content=content if isinstance(content, str) else str(content)),
                HumanMessage(
                    content=(
                        "Your previous output was not valid JSON matching the required "
                        "schema. Output ONLY the JSON object, nothing else."
                    )
                ),
            ]
        return None

    def _build_plan_prompt(self, state: dict[str, Any], *, replan: bool) -> list:
        """Build the planning message list (system + history + instruction)."""
        try:
            schema_text = load_schema_text(source="auto")
        except Exception as exc:  # schema is best-effort context
            logger.warning("Planner: schema load failed: %s", exc)
            schema_text = "(schema unavailable)"

        system = SystemMessage(
            content=(
                "You are the planner for GRASS, an interactive agent for supply chain "
                "analytics over a Neo4j knowledge graph. You devise a concise, ordered "
                "plan that a team of worker agents will execute.\n\n"
                "## Team\n"
                f"{_TEAM_DESCRIPTION}\n\n"
                "## Neo4j Schema\n\n"
                f"{schema_text}\n\n"
                f"{_PLAN_JSON_SCHEMA_INSTRUCTIONS}"
            )
        )

        history = trim_history(list(state.get("messages", [])), MAX_HISTORY_MESSAGES)

        if replan:
            instruction = (
                "We have not been able to make progress with the previous plan, or the "
                "user requested changes. Devise a NEW plan that addresses the feedback.\n\n"
                f"Previous plan:\n{state.get('plan_str', '')}\n\n"
                f"User feedback: {state.get('replan_feedback', '') or '(none given)'}\n\n"
                "Output the plan as the required JSON object."
            )
        else:
            user_query = state.get("user_query", "")
            instruction = (
                f"User request:\n{user_query}\n\n"
                "Decide whether a plan is needed and output the required JSON object."
            )

        return [system, *history, HumanMessage(content=instruction)]
