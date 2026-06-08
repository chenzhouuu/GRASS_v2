"""Scenario Runner — what-if engine (P1, deterministic path).

Re-solves a baseline optimization under a ``Scenario`` (a set of perturbations)
WITHOUT re-formulating: it perturbs the baseline's input data deterministically
and re-runs the baseline's *cached* PuLP code on the perturbed data. This is the
fast, provenance-clean path for numeric what-ifs (demand ±%, capacity changes,
entity removal).

Structural perturbations (constraint/bound edits) are recorded but deferred to
P3 (formulation editing). The before/after comparison + presentation is the
ScenarioInterpreter's job (P2); here we emit a brief inline objective delta.

    runner = ScenarioRunner()
    update = runner.invoke(state)   # needs state["optimization_baseline"] + state["pending_scenario"]
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage

from ..core.schemas import OptimizationRun, Perturbation, Scenario
from ..tools.python_executor import execute_python, persist_cypher_results
from ..tools.scenario_perturbation import apply_perturbations
from .optimization_agent import (
    _build_sankey_from_solution,
    _enrich_solution_coordinates,
    _extract_solution_json,
    _solution_routes_to_geo,
    build_optimization_run,
)
from .scenario_interpreter import build_comparison, build_tornado_spec

logger = logging.getLogger(__name__)


class ScenarioRunner:
    """Deterministic what-if re-solver. Reuses the Optimization agent's
    post-solve builders; no LLM call in the P1 path."""

    agent_name = "scenario_runner"

    def __init__(self, model: Any = None):
        # ``model`` is unused in P1 (deterministic). Reserved for P3 structural
        # perturbations, which edit the formulation via the LLM.
        self.model = model

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        baseline_dict = state.get("optimization_baseline")
        scenario_dict = state.get("pending_scenario")

        if not baseline_dict:
            return self._blocked(
                "No baseline optimization exists yet. Run an optimization first, "
                "then I can compare a what-if scenario against it.",
                state,
            )

        # Sensitivity sweep takes precedence when requested (P3 tornado).
        if state.get("pending_sweep"):
            return self.run_sweep(state)

        if not scenario_dict:
            return self._blocked("No scenario was provided to run.", state)

        baseline = OptimizationRun.model_validate(baseline_dict)
        scenario = Scenario.model_validate(scenario_dict)

        if not baseline.code:
            return self._blocked(
                "The baseline has no cached solver code, so a deterministic "
                "re-solve isn't possible. Re-run the optimization to refresh it.",
                state,
            )

        # 1. Split deterministic vs structural perturbations.
        structural = [p for p in scenario.perturbations if p.kind == "structural"]
        det_perts = [p for p in scenario.perturbations if p.kind != "structural"]
        perturbed, plog = apply_perturbations(baseline.input_data, det_perts)
        logger.info("ScenarioRunner '%s': %s", scenario.name, "; ".join(plog) or "no-op")

        # 2. Re-solve. Deterministic path reuses cached code; structural path
        #    edits the formulation via the LLM and regenerates code (P3).
        formulation_used = baseline.formulation
        code_used = baseline.code
        if structural:
            if self.model is None:
                return self._blocked(
                    "This what-if changes the model structure (a constraint or "
                    "bound), which requires the optimization model. Not available "
                    "in this context.",
                    state,
                )
            instruction = "; ".join(p.instruction for p in structural if p.instruction) \
                or "Apply the requested structural change to the model."
            plog.append(f"structural edit: {instruction[:80]}")
            from .optimization_agent import OptimizationAgent

            res = OptimizationAgent(self.model).resolve_structural_scenario(
                baseline.formulation.model_dump(),
                instruction,
                state.get("user_query", ""),
                perturbed,
            )
            formulation_used = res["formulation"]
            code_used = res["code"] or baseline.code
            solution = res["solution"]
            error = res["error"]
        else:
            solution, error = self._solve(baseline.code, perturbed)

        # 3. Build the scenario run snapshot + post-solve visuals (deterministic).
        chart_specs: list[dict] = []
        geo_data: dict | None = None
        scenario_run: OptimizationRun | None = None
        comparison = None

        if solution and not error:
            solution = _enrich_solution_coordinates(solution)
            scenario_run = build_optimization_run(
                formulation_used, code_used, solution,
                scenario_id=scenario.scenario_id,
            )
            # 4. Before/after comparison (KPI deltas + binding shift + waterfall + narrative).
            comparison = build_comparison(baseline, scenario_run, scenario, model=self.model)
            sankey = _build_sankey_from_solution(solution)
            if sankey:
                chart_specs.append(sankey)
            geo = _solution_routes_to_geo(solution)
            if geo.get("features"):
                geo_data = geo

        summary = self._summary(scenario, baseline, solution, error, plog, comparison)

        update: dict[str, Any] = {
            "messages": [AIMessage(content=summary, name=self.agent_name)],
            "optimization_solution": solution,
            "optimization_error": error,
            "sender": self.agent_name,
            "past_steps": [(f"What-if: {scenario.name}", summary[:400])],
        }
        if scenario_run is not None:
            update["scenario_runs"] = [scenario_run.model_dump()]
        if comparison is not None:
            update["scenario_comparison"] = comparison.model_dump()
        if chart_specs:
            update["chart_specs"] = chart_specs
        if geo_data:
            update["geo_data"] = geo_data
        return update

    # ── helpers ──────────────────────────────────────────────────────

    def _summary(
        self,
        scenario: Scenario,
        baseline: OptimizationRun,
        solution: dict | None,
        error: str | None,
        plog: list[str],
        comparison=None,
    ) -> str:
        lines = [f"**What-if scenario: {scenario.name}**"]
        if scenario.description:
            lines.append(scenario.description)
        lines.append("Perturbations applied: " + ("; ".join(plog) if plog else "none"))

        if error:
            lines.append(f"Scenario re-solve failed: {error[:300]}")
            return "\n".join(lines)
        if not solution:
            lines.append("No solution could be parsed from the scenario re-solve.")
            return "\n".join(lines)

        b_obj, s_obj = baseline.objective, solution.get("objective")
        if isinstance(b_obj, (int, float)) and isinstance(s_obj, (int, float)):
            delta = s_obj - b_obj
            pct = f" ({delta / b_obj * 100:+.1f}%)" if b_obj else ""
            lines.append(
                f"Objective: baseline {b_obj:,.2f} → scenario {s_obj:,.2f} "
                f"(Δ {delta:+,.2f}{pct})"
            )
        else:
            lines.append(f"Scenario objective: {s_obj}")
        if comparison is not None and comparison.narrative:
            lines.append("")
            lines.append(comparison.narrative)
        return "\n".join(lines)

    def _blocked(self, message: str, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content=message, name=self.agent_name)],
            "sender": self.agent_name,
            "worker_feedback": [
                {"type": "scenario_blocked", "agent": "ScenarioRunner", "message": message}
            ],
            "past_steps": [("What-if scenario", message[:200])],
        }

    def _solve(self, code: str, rows: list[dict]) -> tuple[dict | None, str | None]:
        """Run cached solver code against ``rows``; return (solution, error)."""
        persist_cypher_results(rows)
        exec_result = execute_python.invoke({"code": code})
        output = exec_result.get("output") or ""
        error = exec_result.get("error")
        solution = _extract_solution_json(output) if not error else None
        return solution, error

    # ── sensitivity sweep → tornado (P3) ─────────────────────────────

    def run_sweep(self, state: dict[str, Any]) -> dict[str, Any]:
        """One-factor-at-a-time sweep: re-solve the baseline at each factor's
        low/high multiplier and emit a tornado sensitivity chart.

        ``pending_sweep`` shape: {"factors": [{"name", "target", "low", "high",
        "selector"?}]}.
        """
        baseline = OptimizationRun.model_validate(state["optimization_baseline"])
        sweep = state.get("pending_sweep") or {}
        factors = sweep.get("factors") or []

        if not baseline.code:
            return self._blocked("The baseline has no cached code to sweep.", state)
        if not factors:
            return self._blocked("No sweep factors were provided.", state)

        results: list[dict] = []
        for f in factors:
            target = f.get("target", "")
            selector = f.get("selector", {}) or {}
            low_obj = high_obj = None
            if f.get("low") is not None:
                rows, _ = apply_perturbations(
                    baseline.input_data,
                    [Perturbation(kind="scale_param", target=target, factor=float(f["low"]), selector=selector)],
                )
                sol, err = self._solve(baseline.code, rows)
                low_obj = sol.get("objective") if (sol and not err) else None
            if f.get("high") is not None:
                rows, _ = apply_perturbations(
                    baseline.input_data,
                    [Perturbation(kind="scale_param", target=target, factor=float(f["high"]), selector=selector)],
                )
                sol, err = self._solve(baseline.code, rows)
                high_obj = sol.get("objective") if (sol and not err) else None
            results.append({"factor": f.get("name", target), "low_obj": low_obj, "high_obj": high_obj})

        tornado = build_tornado_spec(results, baseline.objective)
        ranked = sorted(
            results,
            key=lambda r: abs((r.get("high_obj") or baseline.objective or 0) - (baseline.objective or 0))
            + abs((r.get("low_obj") or baseline.objective or 0) - (baseline.objective or 0)),
            reverse=True,
        )
        top = ranked[0]["factor"] if ranked else "—"
        summary = (
            f"**Sensitivity sweep** over {len(factors)} factor(s). "
            f"Most influential: **{top}**. See the tornado chart for the objective "
            f"swing of each factor versus the baseline."
        )
        update: dict[str, Any] = {
            "messages": [AIMessage(content=summary, name=self.agent_name)],
            "sender": self.agent_name,
            "past_steps": [("Sensitivity sweep", summary[:300])],
        }
        if tornado:
            update["chart_specs"] = [tornado]
        return update
