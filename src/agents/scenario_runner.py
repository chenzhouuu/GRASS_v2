"""Scenario Runner — what-if engine (P1, deterministic path).

Re-solves a baseline optimization under a ``Scenario`` (a set of perturbations)
WITHOUT re-formulating: it perturbs the baseline's input data deterministically
and re-runs the baseline's *cached* PuLP code on the perturbed data. This is the
fast, provenance-clean path for numeric what-ifs (demand ±%, capacity changes,
entity removal).

Structural perturbations (constraint/bound edits) are recorded but deferred to
P3 (formulation editing). The before/after comparison + presentation is the
ScenarioInterpreter's job (P2); here we emit a brief inline objective delta.

Structural scenarios (``graph_edits``: entity outages) run through the Layer-1
graph-overlay tools (src/tools/graph_scenario.py) and need NO optimization
baseline; numeric perturbations still require one.

    runner = ScenarioRunner()
    update = runner.invoke(state)   # "pending_scenario" optional (plan mode derives it from "worker_task")
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage

from ..core.schemas import OptimizationRun, Perturbation, Scenario
from ..tools.python_executor import (
    execute_python,
    execution_session,
    persist_optimization_input,
)
from ..tools.scenario_perturbation import apply_perturbations
from .optimization_agent import (
    _build_sankey_from_solution,
    _enrich_solution_coordinates,
    _extract_solution_json,
    _solution_routes_to_geo,
    build_optimization_run,
)
from .scenario_interpreter import (
    build_comparison,
    build_structural_comparison,
    build_tornado_spec,
)

logger = logging.getLogger(__name__)

# Elastic diagnostic instruction for infeasible scenarios (CS2 Q2.3 contract:
# report unserved demand and the minimum capacity relaxation, never repair
# silently). The 1e6 weight makes shortfall a last resort, so the relaxation
# total is the minimum capacity addition that restores feasibility.
_ELASTIC_DIAGNOSIS_INSTRUCTION = (
    "The scenario data makes the model INFEASIBLE. Do not repair it silently — "
    "build an ELASTIC DIAGNOSTIC version that quantifies the infeasibility: "
    "(1) add a nonnegative shortfall variable to every demand-satisfaction "
    "constraint; (2) add a nonnegative relaxation variable to every capacity "
    "constraint; (3) replace the objective with: minimize "
    "1000000 * (sum of shortfall variables) + (sum of relaxation variables). "
    "In SOLUTION_JSON report kpis: total_unserved_demand (sum of shortfalls), "
    "unserved_entity_count (number of entities with positive shortfall), and "
    "min_capacity_relaxation (sum of relaxation variables)."
)


class ScenarioRunner:
    """Deterministic what-if re-solver. Reuses the Optimization agent's
    post-solve builders. The deterministic path makes no LLM call; plan-mode
    scenario derivation (when ``pending_scenario`` is absent) calls the model once."""

    agent_name = "scenario_runner"

    def __init__(self, model: Any = None):
        # ``model`` is used for plan-mode scenario derivation (via
        # scenario_from_request) and for P3 structural perturbations.
        # ``model=None`` is only safe in the deterministic direct-mode path
        # where ``pending_scenario`` is already pre-built by the caller.
        self.model = model

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        baseline_dict = state.get("optimization_baseline")
        scenario_dict = state.get("pending_scenario")

        # Sensitivity sweep takes precedence when requested (P3 tornado).
        if state.get("pending_sweep"):
            if not baseline_dict:
                return self._blocked(
                    "A sensitivity sweep re-solves an optimization baseline, and "
                    "none exists yet. Run an optimization first.",
                    state,
                )
            return self.run_sweep(state)

        baseline = (
            OptimizationRun.model_validate(baseline_dict) if baseline_dict else None
        )

        if not scenario_dict:
            # Plan mode: no pre-built scenario — derive one from the step instruction.
            from .scenario_definition import scenario_from_request

            derived = scenario_from_request(
                self.model, state.get("worker_task", "") or "", baseline
            )
            if derived is None:
                return self._blocked(
                    "No scenario was provided, and I couldn't derive a valid "
                    "what-if from the step instruction.",
                    state,
                )
            scenario_dict = derived.model_dump()

        scenario = Scenario.model_validate(scenario_dict)

        # Layer 1: structural graph impact — no optimization baseline required.
        structural_result = None
        if scenario.graph_edits:
            try:
                structural_result = self._run_structural(scenario)
            except ValueError as exc:  # ill-posed edit: unknown/ambiguous entity
                return self._blocked(f"The scenario is not well-posed: {exc}", state)
            except RuntimeError as exc:
                return self._blocked(f"Structural graph analysis failed: {exc}", state)

        if not scenario.perturbations:
            if structural_result is None:
                return self._blocked(
                    "The scenario contains no changes (no perturbations and no "
                    "graph edits).",
                    state,
                )
            return self._structural_update(scenario, structural_result, state)

        # Layer 2: numeric re-solve — requires a baseline with cached code.
        if baseline is None:
            if structural_result is not None:
                return self._structural_update(
                    scenario, structural_result, state,
                    note="The numeric part of this what-if was skipped: no "
                         "optimization baseline exists in this session. Run an "
                         "optimization first for cost/flow deltas.",
                )
            return self._blocked(
                "This what-if changes numeric parameters, which requires a "
                "baseline optimization. Run an optimization first — or ask a "
                "structural question (e.g. 'which farms are stranded if X "
                "closes?'), which needs no baseline.",
                state,
            )

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
                session_id=state.get("session_id"),
            )
            formulation_used = res["formulation"]
            code_used = res["code"] or baseline.code
            solution = res["solution"]
            error = res["error"]
        else:
            if not baseline.input_path:
                return self._blocked(
                    "The saved optimization baseline predates the current data "
                    "layout (it does not record which input file its cached "
                    "code reads), so a re-solve would silently run on "
                    "unperturbed data. Run the optimization once more, then "
                    "repeat the what-if.",
                    state,
                )
            solution, error = self._solve(
                baseline.code, perturbed, state.get("session_id"),
                input_path=baseline.input_path,
            )

        # 2b. Infeasible scenario → quantify (unserved demand + minimum capacity
        # relaxation), never repair silently.
        infeasibility = None
        if "infeasible" in str((solution or {}).get("status", "")).lower():
            infeasibility = self._diagnose_infeasibility(
                scenario, baseline, perturbed, state
            )

        # 3. Build the scenario run snapshot + post-solve visuals (deterministic).
        chart_specs: list[dict] = []
        geo_data: dict | None = None
        scenario_run: OptimizationRun | None = None
        comparison = None

        if solution and not error and infeasibility is None:
            solution = _enrich_solution_coordinates(solution)
            scenario_run = build_optimization_run(
                formulation_used, code_used, solution,
                scenario_id=scenario.scenario_id,
            )
            # 4. Before/after comparison (KPI deltas + binding shift + waterfall + narrative).
            comparison = build_comparison(baseline, scenario_run, scenario, model=self.model)
            if structural_result is not None:
                s_comp = build_structural_comparison(
                    scenario, structural_result["impact"], structural_result["trace"],
                    structural_result["alternatives"],
                )
                comparison.kpi_deltas.extend(s_comp.kpi_deltas)
                comparison.narrative = f"{comparison.narrative} {s_comp.narrative}".strip()
            sankey = _build_sankey_from_solution(solution)
            if sankey:
                chart_specs.append(sankey)
            geo = _solution_routes_to_geo(solution)
            if geo.get("features"):
                geo_data = geo

        summary = self._summary(
            scenario, baseline, solution, error, plog, comparison, infeasibility
        )

        update: dict[str, Any] = {
            "messages": [AIMessage(content=summary, name=self.agent_name)],
            "optimization_solution": solution,
            "optimization_error": error,
            "sender": self.agent_name,
            "past_steps": [(f"What-if: {scenario.name}", summary[:400])],
        }
        if infeasibility is not None:
            update["worker_feedback"] = [{
                "type": "scenario_infeasible",
                "agent": "ScenarioRunner",
                "message": infeasibility["narrative"],
            }]
        if scenario_run is not None:
            update["scenario_runs"] = [scenario_run.model_dump()]
        # A failed or infeasible re-solve still surfaces the structural half.
        if comparison is None and structural_result is not None:
            comparison = build_structural_comparison(
                scenario, structural_result["impact"], structural_result["trace"],
                structural_result["alternatives"],
            )
            if infeasibility is not None:
                comparison.narrative = (
                    f"{comparison.narrative} {infeasibility['narrative']}".strip()
                )
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
        infeasibility: dict | None = None,
    ) -> str:
        lines = [f"**What-if scenario: {scenario.name}**"]
        if scenario.description:
            lines.append(scenario.description)
        lines.append("Perturbations applied: " + ("; ".join(plog) if plog else "none"))

        if infeasibility is not None:
            lines.append(infeasibility["narrative"])
            return "\n".join(lines)
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

    def _diagnose_infeasibility(
        self,
        scenario: Scenario,
        baseline: OptimizationRun,
        perturbed_rows: list[dict],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Elastic diagnostic re-solve quantifying an infeasible scenario.

        Reuses the structural-scenario pipeline (formulation edit + codegen)
        with a fixed elastic instruction. Best-effort: without a model, or if
        the diagnostic solve itself fails, a plain statement is returned.
        """
        plain = {
            "kpis": {},
            "narrative": (
                "The scenario makes the baseline plan infeasible: demand can no "
                "longer be fully met with the given capacities."
            ),
        }
        if self.model is None:
            return plain

        from .optimization_agent import OptimizationAgent

        try:
            res = OptimizationAgent(self.model).resolve_structural_scenario(
                baseline.formulation.model_dump(),
                _ELASTIC_DIAGNOSIS_INSTRUCTION,
                state.get("user_query", ""),
                perturbed_rows,
                session_id=state.get("session_id"),
            )
        except Exception as exc:  # noqa: BLE001 — diagnosis is best-effort
            logger.warning("Infeasibility diagnosis failed: %s", exc)
            return plain

        sol = res.get("solution") or {}
        kpis = sol.get("kpis") or {}
        if res.get("error") or not kpis:
            return plain

        lines = [plain["narrative"], "Elastic diagnosis:"]
        relax = kpis.get("min_capacity_relaxation")
        unserved = kpis.get("total_unserved_demand")
        n_short = kpis.get("unserved_entity_count")
        if relax is not None:
            lines.append(
                f"restoring feasibility requires at least {relax:,.0f} units of "
                f"additional capacity;"
            )
        if unserved:
            suffix = f" across {int(n_short)} entities" if n_short else ""
            lines.append(
                f"{unserved:,.0f} units of demand remain unserved{suffix} even "
                f"after that relaxation."
            )
        elif relax is not None:
            lines.append("all demand can be served once that capacity is added.")
        return {"kpis": kpis, "narrative": " ".join(lines)}

    def _run_structural(self, scenario: Scenario) -> dict[str, Any]:
        """Layer-1 deterministic graph analysis for the scenario's edits."""
        from ..tools.graph_scenario import (
            cascade_trace,
            nearest_alternatives,
            structural_impact,
        )

        return {
            "impact": structural_impact(scenario.graph_edits),
            "trace": cascade_trace(scenario.graph_edits),
            "alternatives": nearest_alternatives(scenario.graph_edits),
        }

    def _structural_update(
        self,
        scenario: Scenario,
        structural: dict[str, Any],
        state: dict[str, Any],
        note: str | None = None,
    ) -> dict[str, Any]:
        """State update for a structural-only what-if (no LP re-solve)."""
        comparison = build_structural_comparison(
            scenario, structural["impact"], structural["trace"],
            structural["alternatives"],
        )
        summary = f"**What-if scenario: {scenario.name}**\n{comparison.narrative}"
        if note:
            summary += f"\n\n{note}"
        update: dict[str, Any] = {
            "messages": [AIMessage(content=summary, name=self.agent_name)],
            "sender": self.agent_name,
            "scenario_comparison": comparison.model_dump(),
            "past_steps": [(f"What-if: {scenario.name}", summary[:400])],
        }
        if note:
            update["worker_feedback"] = [{
                "type": "scenario_partial", "agent": "ScenarioRunner", "message": note,
            }]
        return update

    def _blocked(self, message: str, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "messages": [AIMessage(content=message, name=self.agent_name)],
            "sender": self.agent_name,
            "worker_feedback": [
                {"type": "scenario_blocked", "agent": "ScenarioRunner", "message": message}
            ],
            "past_steps": [("What-if scenario", message[:200])],
        }

    def _solve(
        self,
        code: str,
        rows: list[dict],
        session_id: str | None = None,
        input_path: str | None = None,
    ) -> tuple[dict | None, str | None]:
        """Run cached solver code against ``rows``; return (solution, error).

        The rows must go to the exact input file the cached code reads —
        that path was baked in at codegen time and is recorded in the
        baseline's ``input_path``.
        """
        persist_optimization_input(rows, session_id, rel_path=input_path)
        with execution_session(session_id):
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
        if not baseline.input_path:
            return self._blocked(
                "The saved optimization baseline predates the current data "
                "layout and cannot be swept safely. Run the optimization once "
                "more, then repeat the sweep.",
                state,
            )
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
                sol, err = self._solve(
                    baseline.code, rows, state.get("session_id"),
                    input_path=baseline.input_path,
                )
                low_obj = sol.get("objective") if (sol and not err) else None
            if f.get("high") is not None:
                rows, _ = apply_perturbations(
                    baseline.input_data,
                    [Perturbation(kind="scale_param", target=target, factor=float(f["high"]), selector=selector)],
                )
                sol, err = self._solve(
                    baseline.code, rows, state.get("session_id"),
                    input_path=baseline.input_path,
                )
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
