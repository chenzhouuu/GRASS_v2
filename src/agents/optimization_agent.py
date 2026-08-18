"""Optimization Agent — 4-stage Adapted OptiMUS pipeline.

Decomposes supply chain optimization into:
  Stage 1: Formulate (structured output → OptimizationFormulation)
  Stage 2: Validate  (deterministic column/scale checks)
  Stage 3: Generate  (LLM writes PuLP code from formulation)
  Stage 4: Execute   (subprocess + error correction + post-solve viz)

Falls back to single-shot code generation if the pipeline fails.

Design informed by:
- OptiMUS (Stanford, ICML 2024): staged decomposition, structured formulation
- OR-LLM-Agent (2025): reasoning-first, then code
- LLMOPT (Ant Group, ICLR 2025): five-element universal formulation

    agent = OptimizationAgent(model)
    result = agent.invoke(state)
"""

import json
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..core.schemas import KPI, OptimizationFormulation, OptimizationRun
from ..tools.python_executor import (
    execute_python,
    execution_session,
    persist_optimization_input,
)
from ..tools.session_workspace import gather_tagged_rows, get_workspace
from ..utils.data_summarizer import summarize_data, format_summary_for_prompt, make_data_preview
from ..utils.prompt_loader import load_prompt
from ..utils.plotly_markers import (
    PLOTLY_PATTERN,
    extract_plotly_specs,
    strip_plotly_markers,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_FORMULATION_RETRIES = 2
_MODIFY_PREFIX = "MODIFY_PREVIOUS:"

_SOLUTION_JSON_LINE = re.compile(r"SOLUTION_JSON:[^\n]*")
_MAX_OBSERVATION_CHARS = 4_000


def _compact_execution_observation(tool_result: Any) -> str:
    """Compact execute_python output before it enters the LLM context.

    The full stdout stays in ``last_output`` for programmatic parsing
    (SOLUTION_JSON extraction, degeneracy checks, chart specs); the model
    only needs the human-readable solver lines, not the machine-readable
    blobs, which dominated a traced 27.6k-token prompt for a 94-token
    summary reply.
    """
    if not isinstance(tool_result, dict):
        return str(tool_result)
    compact = dict(tool_result)
    output = compact.get("output") or ""
    if output:
        output = PLOTLY_PATTERN.sub("[chart spec captured]", output)
        output = _SOLUTION_JSON_LINE.sub(
            "[SOLUTION_JSON captured — parsed programmatically]", output
        )
        if len(output) > _MAX_OBSERVATION_CHARS:
            output = output[:_MAX_OBSERVATION_CHARS] + "\n... [output truncated]"
        compact["output"] = output
    return str(compact)

class _PipelineExhaustedError(Exception):
    """Raised when the 4-stage pipeline exhausts all retries."""


# ── Post-solve deterministic builders ────────────────────────────────


_SANKEY_MAX_ROUTES = 30
_SANKEY_MIN_VOLUME_PCT = 0.01  # drop routes < 1% of max volume


def _build_sankey_from_solution(solution: dict) -> dict | None:
    """Build Plotly Sankey diagram deterministically from solution routes.

    Filters to top-N routes by volume and drops tiny flows for readability.
    """
    routes = solution.get("routes", [])
    if len(routes) < 2:
        return None

    # Filter: drop routes with zero/missing volume
    routes = [r for r in routes if r.get("volume", 0) > 0]
    if len(routes) < 2:
        return None

    # Filter: drop routes below 1% of max volume
    max_vol = max(r.get("volume", 0) for r in routes)
    if max_vol > 0:
        threshold = max_vol * _SANKEY_MIN_VOLUME_PCT
        routes = [r for r in routes if r.get("volume", 0) >= threshold]

    # Sort by volume descending, keep top-N
    routes = sorted(routes, key=lambda r: r.get("volume", 0), reverse=True)
    routes = routes[:_SANKEY_MAX_ROUTES]

    if len(routes) < 2:
        return None

    labels: list[str] = []
    label_idx: dict[str, int] = {}
    for r in routes:
        for key in ("from", "to"):
            name = r.get(key, "")
            if name and name not in label_idx:
                label_idx[name] = len(labels)
                labels.append(name)

    if len(labels) < 2:
        return None

    source_names = {r.get("from", "") for r in routes}
    colors = ["#16a34a" if label in source_names else "#2563eb" for label in labels]

    source = [label_idx[r["from"]] for r in routes if r.get("from") in label_idx]
    target = [label_idx[r["to"]] for r in routes if r.get("to") in label_idx]
    value = [r.get("volume", 0) for r in routes if r.get("from") in label_idx]

    if not source:
        return None

    total_vol = sum(value)
    height = max(400, len(labels) * 25 + 100)

    return {
        "data": [{
            "type": "sankey",
            "node": {
                "label": labels,
                "color": colors,
                "pad": 20,
                "thickness": 20,
            },
            "link": {
                "source": source,
                "target": target,
                "value": value,
                "color": [
                    "rgba(22, 163, 74, 0.35)"  # semi-transparent green
                    for _ in source
                ],
            },
        }],
        "layout": {
            "title": {"text": f"Optimal Supply Chain Flows ({len(routes)} routes, {total_vol:,.0f} lbs total)"},
            "font": {"size": 11},
            "height": height,
        },
    }


def _enrich_solution_coordinates(solution: dict) -> dict:
    """Resolve origin/dest coordinates from entity names via Neo4j.

    Decouples geographic data from Cypher query output.
    The optimization code focuses on optimization — geography
    is handled deterministically by name lookup.
    """
    from ..utils.neo4j_connection import get_session

    routes = solution.get("routes", [])
    if not routes:
        return solution

    # Collect all entity names that need coordinates
    names = set()
    for route in routes:
        names.add(route.get("from", ""))
        names.add(route.get("to", ""))
    names.discard("")

    if not names:
        return solution

    # Single Neo4j lookup for all entities with coordinates
    coord_map: dict[str, tuple[float, float]] = {}
    try:
        with get_session() as session:
            result = session.run(
                "MATCH (n) WHERE n.name IN $names AND n.lat IS NOT NULL "
                "RETURN n.name AS name, n.lat AS lat, n.lon AS lon",
                {"names": list(names)},
            )
            for record in result:
                coord_map[record["name"]] = (record["lat"], record["lon"])
        logger.info(
            "Coordinate enrichment: resolved %d/%d entity names",
            len(coord_map), len(names),
        )
    except Exception as exc:
        logger.warning("Coordinate enrichment failed: %s", exc)
        return solution

    # Enrich routes — overwrite LLM-provided coords with authoritative ones
    for route in routes:
        origin = route.get("from", "")
        dest = route.get("to", "")
        if origin in coord_map:
            route["origin_lat"], route["origin_lon"] = coord_map[origin]
        if dest in coord_map:
            route["dest_lat"], route["dest_lon"] = coord_map[dest]

    return solution


def _solution_routes_to_geo(solution: dict) -> dict:
    """Convert optimization routes to GeoJSON FeatureCollection.

    Uses OSRM to resolve real road geometry when available.
    Falls back to straight-line if OSRM fails.
    """
    from ..utils.route_resolver import resolve_routes_batch

    raw_routes = [
        r for r in solution.get("routes", [])
        if all(k in r for k in ("origin_lat", "origin_lon", "dest_lat", "dest_lon"))
    ]

    if not raw_routes:
        return {"type": "FeatureCollection", "features": []}

    # Resolve real road geometry via OSRM (top 20 routes)
    resolved = resolve_routes_batch(raw_routes, max_routes=20)

    features = []
    for route in resolved:
        road_geom = route.get("road_geometry")

        if road_geom and len(road_geom) >= 2:
            # Real road geometry from OSRM (400+ coordinate points)
            coordinates = road_geom
        else:
            # Fallback: straight line (2 points)
            coordinates = [
                [route["origin_lon"], route["origin_lat"]],
                [route["dest_lon"], route["dest_lat"]],
            ]

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coordinates,
            },
            "properties": {
                "origin_name": route.get("from", ""),
                "dest_name": route.get("to", ""),
                "volume_lbs": route.get("volume", 0),
                "cost": route.get("cost", 0),
                "type": "optimization_route",
            },
        })

    return {"type": "FeatureCollection", "features": features}


def _extract_solution_json(output: str) -> dict | None:
    """Parse SOLUTION_JSON block from stdout.

    Handles multiple formatting variants the LLM might produce:
    - Single-line: SOLUTION_JSON:{...}
    - Multi-line: SOLUTION_JSON: followed by JSON on next lines
    - With or without space after colon
    - JSON that spans multiple lines
    """
    # Strategy 1: find SOLUTION_JSON: marker and extract everything after it as JSON
    marker_pos = output.find("SOLUTION_JSON:")
    if marker_pos >= 0:
        after_marker = output[marker_pos + len("SOLUTION_JSON:"):].strip()
        # Find the JSON object — look for balanced braces
        if after_marker.startswith("{"):
            depth = 0
            for i, ch in enumerate(after_marker):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(after_marker[: i + 1])
                        except json.JSONDecodeError:
                            break

    # Strategy 2: find any JSON object in the output that has "status" key
    # (covers cases where SOLUTION_JSON marker is malformed)
    for match in re.finditer(r"\{[^{}]*\"status\"[^{}]*\}", output):
        try:
            candidate = json.loads(match.group(0))
            if "status" in candidate:
                return candidate
        except json.JSONDecodeError:
            continue

    # Strategy 3: find any large JSON object (>50 chars) that looks like a solution
    for match in re.finditer(r"\{.{50,}\}", output, re.DOTALL):
        try:
            candidate = json.loads(match.group(0))
            if isinstance(candidate, dict) and ("routes" in candidate or "objective" in candidate):
                return candidate
        except json.JSONDecodeError:
            continue

    # Strategy 4: extract status + objective from text even without valid JSON
    status_match = re.search(r"Status:\s*(Optimal|Infeasible|Unbounded)", output)
    obj_match = re.search(r"(?:Objective|Optimal|Total)[^:]*:\s*\$?([\d,.]+)", output)
    if status_match:
        result: dict = {"status": status_match.group(1)}
        if obj_match:
            try:
                result["objective"] = float(obj_match.group(1).replace(",", ""))
            except ValueError:
                pass
        result["routes"] = []
        result["sensitivity"] = []
        logger.info("Extracted partial solution from text (no valid SOLUTION_JSON)")
        return result

    return None


def _is_degenerate_output(output: str | None) -> bool:
    """True when stdout holds an Optimal solution that shipped nothing (objective 0,
    no routes) — the signature of an under-constrained min-cost LP."""
    sol = _extract_solution_json(output or "")
    if not sol:
        return False
    status = str(sol.get("status", "")).lower()
    return status.startswith("optimal") and not (sol.get("routes") or []) and not sol.get("objective")


# Corrective injected when a solve comes back degenerate (solution-level, robust).
_DEGENERATE_CORRECTION = (
    "The model returned objective 0 with NO allocations — it is DEGENERATE. You used "
    "only upper-bound (<=) constraints, so shipping/allocating nothing is trivially "
    "optimal. Fix it with a flow-forcing constraint that is GUARANTEED FEASIBLE: require "
    "each processor to receive AT LEAST its CURRENT contracted intake = sum of the "
    "existing SUPPLIES_RAW_MILK volume_lbs_month into it (for each j: sum_i x[i,j] >= "
    "demand[j], where demand[j] is that current intake). Keep <= cooperative supply and "
    "<= processor capacity (processing_capacity_lbs_day*30) as bounds. The current edge "
    "volumes are a feasible point, so this MUST be feasible. Regenerate and execute again."
)

# Corrective injected when the solve is INFEASIBLE (usually an over-tight flow constraint
# or an annual-vs-monthly units mismatch).
_INFEASIBLE_CORRECTION = (
    "The model is INFEASIBLE — your flow constraint over-constrains it. Do NOT force FULL "
    "cooperative supply (sum_j x[i,j] == supply[i]); total monthly supply often exceeds "
    "reachable capacity (watch annual-vs-monthly units — divide annual figures by 12). "
    "Instead: (a) cap each cooperative outflow at its MONTHLY supply, (b) cap each "
    "processor inflow at processing_capacity_lbs_day*30, (c) require each processor to "
    "receive AT LEAST its CURRENT contracted intake (sum of existing SUPPLIES_RAW_MILK "
    "volume_lbs_month into it) — always feasible — and minimize hauling cost. Regenerate "
    "and execute again."
)


def _deterministic_opt_summary(last_output: str | None, last_error: str | None) -> str:
    """Compose the worker's final message from the parsed solution.

    Replaces the trailing 'Summarize the optimization results.' LLM call,
    which re-read the whole codegen conversation (traced: 27.6k prompt
    tokens for a 94-token reply).
    """
    if last_error:
        return f"Optimization code execution failed: {last_error[:500]}"
    solution = _extract_solution_json(last_output or "")
    if not solution:
        return (
            "Optimization run completed but no SOLUTION_JSON was found "
            "in the output."
        )
    parts = [f"Optimization complete: status {solution.get('status', 'unknown')}"]
    objective = solution.get("objective")
    if isinstance(objective, (int, float)):
        parts.append(f"objective {objective:,.2f}")
    routes = solution.get("routes") or []
    if isinstance(routes, list) and routes:
        parts.append(f"{len(routes)} active route(s)")
    binding = solution.get("binding") or []
    if isinstance(binding, list) and binding:
        parts.append(f"binding: {', '.join(str(b) for b in binding[:5])}")
    return "; ".join(parts) + "."


def _is_infeasible_output(output: str | None) -> bool:
    """True when the parsed solution reports an infeasible/unbounded status."""
    sol = _extract_solution_json(output or "")
    if not sol:
        return False
    return str(sol.get("status", "")).lower().startswith(("infeasible", "unbounded"))


def _extract_json_from_text(text: str) -> dict:
    """Extract JSON object from LLM text response (fallback for structured output)."""
    # Try parsing the whole thing
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting from markdown code blocks
    code_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass
    # Find outermost { ... }
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in LLM response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    break
    raise ValueError("Could not extract valid JSON from LLM response")


def _estimate_model_points(formulation: OptimizationFormulation, total_rows: int) -> int:
    """Estimate how many supply/demand points the formulation will produce.

    Used to catch over-aggressive data reduction before code generation.
    """
    dr = formulation.data_reduction.lower()
    if "aggregate" in dr:
        if "cooperative" in dr or "coop" in dr:
            return min(12, total_rows)  # PA has ~12 cooperatives
        if "county" in dr:
            return min(50, total_rows)  # PA has ~67 counties
    if "top" in dr or "filter" in dr:
        # Extract N from "top N" or "top-N"
        import re
        match = re.search(r"top[- ]?(\d+)", dr)
        if match:
            return int(match.group(1))
        return max(20, total_rows // 10)
    return total_rows


def _coerce_formulation_json(d: dict) -> dict:
    """Coerce a raw JSON dict into OptimizationFormulation shape.

    LLMs frequently use 'description' instead of 'definition', omit
    required fields, or use slightly different structures.  This
    normaliser fills defaults and renames common aliases so that
    ``model_validate`` can succeed.
    """
    # Unwrap a single top-level wrapper key (e.g. {"optimization_formulation": {...}}).
    for wrapper in ("optimization_formulation", "formulation", "OptimizationFormulation"):
        if isinstance(d.get(wrapper), dict) and len(d) == 1:
            d = dict(d[wrapper])
            break

    # Aliases: 'type' -> problem_type, 'decision_variables' -> variables.
    if "problem_type" not in d and isinstance(d.get("type"), str):
        d["problem_type"] = d.pop("type")
    if "variables" not in d and "decision_variables" in d:
        d["variables"] = d.pop("decision_variables")

    # Map a free-form problem_type onto the allowed enum.
    _allowed_pt = {"transportation", "facility_location", "inventory", "assignment", "routing", "blending", "custom"}
    pt = str(d.get("problem_type", "custom")).lower()
    if pt not in _allowed_pt:
        d["problem_type"] = (
            "transportation" if "transport" in pt
            else "facility_location" if ("facility" in pt or "location" in pt)
            else "assignment" if "assign" in pt
            else "custom"
        )

    # sets/parameters/variables sometimes arrive as a LIST of {name, ...} objects.
    for section in ("sets", "parameters", "variables"):
        val = d.get(section)
        if isinstance(val, list):
            as_dict: dict = {}
            for i, item in enumerate(val):
                if isinstance(item, dict):
                    key = item.get("name") or item.get("symbol") or f"{section[:-1]}_{i}"
                    item = {k: v for k, v in item.items() if k not in ("name", "symbol")}
                    as_dict[str(key)] = item
            d[section] = as_dict

    # assumptions as a list of dicts -> list of strings.
    if isinstance(d.get("assumptions"), list):
        d["assumptions"] = [
            a if isinstance(a, str)
            else str(a.get("item") or a.get("name") or a.get("source_value") or json.dumps(a, default=str))
            for a in d["assumptions"]
        ]

    d.setdefault("problem_type", "custom")
    d.setdefault("description", "Optimization problem")
    d.setdefault("sets", {})
    d.setdefault("parameters", {})
    d.setdefault("variables", {})
    d.setdefault("constraints", [])
    d.setdefault("assumptions", [] if not isinstance(d.get("assumptions"), list) else d["assumptions"])
    d.setdefault("data_reduction", "")

    # If assumptions is a dict instead of list, convert
    if isinstance(d.get("assumptions"), dict):
        d["assumptions"] = [f"{k}: {v}" for k, v in d["assumptions"].items()]

    # Coerce objective
    obj = d.get("objective")
    if isinstance(obj, str):
        d["objective"] = {"sense": "minimize", "expression": obj}
    elif obj is None:
        d["objective"] = {"sense": "minimize", "expression": "unknown"}

    # Coerce nested dicts: sets, parameters, variables
    # LLM often uses 'description' instead of 'definition'
    _allowed_src = {"column", "computed", "constant", "estimated"}
    for section in ("sets", "parameters", "variables"):
        items = d.get(section)
        if isinstance(items, dict):
            for key, val in list(items.items()):
                # A value given as a list (e.g. ['name', 'description']) -> dict.
                if isinstance(val, list):
                    val = {"definition": " ".join(str(x) for x in val)}
                    items[key] = val
                if isinstance(val, dict):
                    # description → definition
                    if "definition" not in val and "description" in val:
                        val["definition"] = val.pop("description")
                    val.setdefault("definition", key)
                    # sets need size_from
                    if section == "sets":
                        val.setdefault("size_from", val.get("source_value", "unknown"))
                    # parameters need a VALID source_type + source_value
                    if section == "parameters":
                        if val.get("source_type") not in _allowed_src:
                            val["source_type"] = "estimated"
                        val.setdefault("source_value", val.get("definition", ""))
                    # variables need type + bounds (string)
                    if section == "variables":
                        val.setdefault("type", "continuous")
                        val.setdefault("bounds", ">= 0")
                        # LLMs often return bounds as list [0, "infinity"]
                        if not isinstance(val.get("bounds"), str):
                            raw = val["bounds"]
                            if isinstance(raw, list) and len(raw) == 2:
                                lo, hi = raw
                                val["bounds"] = f">= {lo}" if str(hi).lower() in ("inf", "infinity", "none") else f"{lo} <= x <= {hi}"
                            else:
                                val["bounds"] = str(raw)

    # Coerce constraints list
    if isinstance(d.get("constraints"), list):
        for i, c in enumerate(d["constraints"]):
            if isinstance(c, dict):
                c.setdefault("name", c.get("type", f"constraint_{i}"))
                c.setdefault("expression", c.get("description", ""))

    return d


def _classify_opt_error(error: str, formulation: OptimizationFormulation | None) -> str:
    """Optimization-specific error hints."""
    e = error.lower()
    if "infeasible" in e:
        constraints = [c.name for c in formulation.constraints] if formulation else []
        return (
            "Model is infeasible. Check: total supply >= total demand? "
            f"Constraints: {constraints}. Try relaxing or adding slack variables."
        )
    if "unbounded" in e:
        return "Model is unbounded. Add upper bounds or check objective sign."
    if "keyerror" in e:
        return "Column not found. Check data columns match formulation parameters."
    if "syntaxerror" in e and "unterminated string" in e:
        return "Do NOT use literal newlines in f-strings. Use \\n."
    if "pulp" in e and ("variable" in e or "name" in e):
        return "PuLP variable name error. Use integer indices (0,1,2), NOT entity names."
    if "modulenotfounderror" in e:
        return "Use only: pulp, pandas, numpy, math, json, shutil."
    return "Review the traceback and fix the issue."


# ── What-if baseline snapshot builders (deterministic, no LLM) ───────


_BINDING_SLACK_EPS = 1e-3


def _derive_kpis(solution: dict) -> list[dict]:
    """Derive normalized KPIs from a solution dict (deterministic).

    Combines structural KPIs (objective, total volume/cost, route count)
    with any explicit ``kpis`` dict the generated code emitted. Explicit
    values take precedence over derived ones of the same name.
    """
    kpis: dict[str, dict] = {}

    obj = solution.get("objective")
    if isinstance(obj, (int, float)):
        kpis["objective_value"] = {"name": "objective_value", "value": float(obj), "unit": ""}

    routes = solution.get("routes") or []
    if routes:
        total_vol = sum(r.get("volume", 0) or 0 for r in routes)
        total_cost = sum(r.get("cost", 0) or 0 for r in routes)
        kpis["total_volume"] = {"name": "total_volume", "value": float(total_vol), "unit": "lbs"}
        kpis["total_route_cost"] = {"name": "total_route_cost", "value": float(total_cost), "unit": "$"}
        kpis["n_active_routes"] = {"name": "n_active_routes", "value": float(len(routes)), "unit": ""}

    explicit = solution.get("kpis")
    if isinstance(explicit, dict):
        for key, val in explicit.items():
            if isinstance(val, (int, float)):
                kpis[str(key)] = {"name": str(key), "value": float(val), "unit": ""}

    return list(kpis.values())


def _extract_duals(solution: dict) -> dict:
    """Constraint name → shadow price. Prefer explicit ``duals``, else derive from ``sensitivity``."""
    duals = solution.get("duals")
    if isinstance(duals, dict) and duals:
        return {str(k): float(v) for k, v in duals.items() if isinstance(v, (int, float))}
    out: dict[str, float] = {}
    for s in solution.get("sensitivity") or []:
        if isinstance(s, dict) and "constraint" in s and isinstance(s.get("shadow_price"), (int, float)):
            out[str(s["constraint"])] = float(s["shadow_price"])
    return out


def _extract_binding(solution: dict) -> list[str]:
    """Binding constraint names. Prefer explicit ``binding``, else slack≈0 in ``sensitivity``."""
    binding = solution.get("binding")
    if isinstance(binding, list) and binding:
        return [str(b) for b in binding]
    out: list[str] = []
    for s in solution.get("sensitivity") or []:
        if isinstance(s, dict) and "constraint" in s:
            slack = s.get("slack")
            if isinstance(slack, (int, float)) and abs(slack) <= _BINDING_SLACK_EPS:
                out.append(str(s["constraint"]))
    return out


def build_optimization_run(
    formulation: OptimizationFormulation,
    code: str,
    solution: dict | None,
    scenario_id: str | None = None,
    run_id: str | None = None,
    input_data: list[dict] | None = None,
    input_path: str = "",
) -> OptimizationRun:
    """Assemble an OptimizationRun snapshot from a formulation + solution (deterministic).

    The baseline run caches ``code`` and ``input_data`` so a later scenario can
    re-solve on perturbed data without re-formulating.
    """
    sol = solution or {}
    obj = sol.get("objective")
    return OptimizationRun(
        run_id=run_id or uuid.uuid4().hex[:8],
        scenario_id=scenario_id,
        formulation=formulation,
        code=code or "",
        status=str(sol.get("status", "")),
        objective=float(obj) if isinstance(obj, (int, float)) else None,
        kpis=[KPI(**k) for k in _derive_kpis(sol)],
        duals=_extract_duals(sol),
        binding_constraints=_extract_binding(sol),
        routes=sol.get("routes") or [],
        input_data=input_data or [],
        input_path=input_path,
    )


def _collect_input_rows(state: dict[str, Any]) -> list[dict]:
    """All retrieval steps' rows, flat and step-tagged.

    Workspace mode reads the session's named tables (P2-c); without a
    workspace (benchmarks, tests) fall back to the state-accumulated rows.
    """
    workspace = get_workspace(state.get("session_id"))
    if workspace:
        rows = gather_tagged_rows(workspace.catalog())
        if rows:
            return rows
    return state.get("all_query_results") or state.get("cypher_results") or []


# ── Agent class ──────────────────────────────────────────────────────


class OptimizationAgent:
    """Optimization Agent with 4-stage pipeline and single-shot fallback.

    Parameters
    ----------
    model : BaseChatModel
        A LangChain chat model that supports tool calling.
    """

    agent_name = "optimization_agent"

    def __init__(self, model):
        self.tools = [execute_python]
        self._raw_model = model
        self.model = model.bind_tools(self.tools)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run optimization. Tries 4-stage pipeline, falls back to single-shot."""
        try:
            return self._run_pipeline(state)
        except _PipelineExhaustedError as exc:
            logger.warning("Pipeline failed (%s), falling back to single-shot", exc)
            return self._run_single_shot(state)
        except Exception as exc:
            logger.warning("Pipeline error (%s: %s), falling back to single-shot", type(exc).__name__, exc)
            return self._run_single_shot(state)

    # ── 4-Stage Pipeline ─────────────────────────────────────────────

    def _run_pipeline(self, state: dict[str, Any]) -> dict[str, Any]:
        cypher_results = _collect_input_rows(state)
        data_path = persist_optimization_input(cypher_results, state.get("session_id"))
        task = state.get("worker_task") or "Formulate and solve an optimization problem."
        user_query = state.get("user_query", "")

        # Data context
        data_summary = summarize_data(cypher_results)
        data_context = format_summary_for_prompt(data_summary)
        data_preview = make_data_preview(cypher_results, max_rows=3)

        # ── Stage 1: Formulate ───────────────────────────────────
        if task.startswith(_MODIFY_PREFIX) and state.get("optimization_model"):
            # What-if: modify existing formulation
            modification = task[len(_MODIFY_PREFIX):].strip()
            base = OptimizationFormulation.model_validate(state["optimization_model"])
            formulation = self._modify_formulation(base, modification)
        else:
            formulation = self._run_stage1(task, user_query, data_context, data_summary)

        # ── Stage 3: Generate Code ───────────────────────────────
        code_result = self._run_stage3(
            formulation, data_preview, user_query, data_path,
            session_id=state.get("session_id"),
        )

        # ── Stage 4: Post-process ────────────────────────────────
        return self._build_result(
            formulation, code_result, state,
            input_rows=cypher_results, input_path=data_path,
        )

    def _run_stage1(
        self, task: str, user_query: str, data_context: str, data_summary: dict,
    ) -> OptimizationFormulation:
        """Stage 1: Produce structured formulation with validation loop."""
        template = load_prompt("optimization_formulate.txt")
        prompt_text = template.replace("{data_summary}", data_context).replace("{task}", task)

        messages = [
            SystemMessage(content=prompt_text),
            HumanMessage(content=f"User question: {user_query}\n\nTask: {task}"),
        ]

        for attempt in range(MAX_FORMULATION_RETRIES + 1):
            formulation = self._formulate(messages)

            # Stage 2: Validate
            issues = self._validate_formulation(formulation, data_summary)
            if not issues:
                logger.info("Stage 1 formulation validated (attempt %d)", attempt + 1)
                return formulation

            logger.warning("Formulation validation issues (attempt %d): %s", attempt + 1, issues)
            if attempt < MAX_FORMULATION_RETRIES:
                messages.append(AIMessage(content=formulation.model_dump_json(indent=2)))
                messages.append(HumanMessage(content=(
                    "Validation found issues:\n" + "\n".join(f"- {i}" for i in issues) +
                    "\n\nFix these issues and produce an updated formulation."
                )))

        raise _PipelineExhaustedError(f"Formulation failed validation after {MAX_FORMULATION_RETRIES + 1} attempts")

    def _formulate(self, messages: list) -> OptimizationFormulation:
        """Produce structured formulation. Tries function_calling, falls back to JSON extraction."""
        # Try structured output with function_calling method (more lenient than json_schema)
        for method in ("function_calling", "json_mode"):
            try:
                formulation_model = self._raw_model.with_structured_output(
                    OptimizationFormulation, method=method,
                )
                return formulation_model.invoke(messages)
            except Exception as exc:
                logger.warning("Structured output (%s) failed: %s", method, exc)

        # Final fallback: raw text + JSON extraction + lenient validation
        logger.info("All structured output methods failed, trying raw JSON extraction")
        raw_response = self._raw_model.invoke(messages)
        content = raw_response.content if hasattr(raw_response, "content") else str(raw_response)
        json_dict = _extract_json_from_text(content)

        json_dict = _coerce_formulation_json(json_dict)
        return OptimizationFormulation.model_validate(json_dict)

    def _validate_formulation(
        self, formulation: OptimizationFormulation, data_summary: dict,
    ) -> list[str]:
        """Stage 2: Deterministic validation."""
        issues = []
        field_names_lower = {f.lower() for f in data_summary.get("field_names", [])}

        for name, param in formulation.parameters.items():
            if param.source_type == "column":
                if param.source_value.lower() not in field_names_lower:
                    issues.append(
                        f"Parameter '{name}' references column '{param.source_value}' "
                        f"not found. Available: {data_summary.get('field_names', [])}"
                    )

        total_rows = data_summary.get("total_rows", 0)
        if total_rows > 500 and not formulation.data_reduction:
            issues.append(
                f"Data has {total_rows} rows but no data_reduction strategy. "
                f"Aggregate by county/cooperative or filter top-N."
            )

        # Facility location (weighted centroid) doesn't need LP variables/constraints
        is_facility_location = formulation.problem_type == "facility_location"

        if not formulation.variables and not is_facility_location:
            issues.append("Formulation has no decision variables.")
        if not formulation.constraints and not is_facility_location:
            issues.append("Formulation has no constraints.")

        # Model size estimation: reject over-aggregation
        if formulation.data_reduction and total_rows > 0:
            estimated = _estimate_model_points(formulation, total_rows)
            if estimated < 5:
                issues.append(
                    f"Data reduction would produce ~{estimated} supply/demand points — "
                    f"too few for meaningful optimization. Use top-N filtering "
                    f"(e.g., top 30-50 entities by production volume) instead of "
                    f"full aggregation. Original data has {total_rows} rows."
                )

        # Degenerate min-cost guard: a MINIMIZE problem whose constraints are ALL
        # upper bounds (<=) has a trivial zero-flow optimum (ship/allocate nothing
        # → cost 0). Require a flow-forcing constraint (supply fully allocated or
        # demand met). This is the #1 cause of a "$0, no routes" solution.
        if (
            formulation.objective
            and formulation.objective.sense == "minimize"
            and formulation.variables
            and formulation.constraints
            and not is_facility_location
        ):
            exprs = " ".join((c.expression or "") for c in formulation.constraints)
            stripped = exprs.replace("<=", "").replace(">=", "").replace("=<", "").replace("=>", "")
            has_forcing = (
                ">=" in exprs
                or "≥" in exprs           # ≥
                or "=>" in exprs
                or "=" in stripped              # a bare equality constraint
                or any(w in exprs.lower() for w in (
                    "at least", "exactly", "fully", "meet demand", "satisfy",
                    "all supply", "balance", "equal",
                ))
            )
            if not has_forcing:
                issues.append(
                    "Degenerate min-cost model: every constraint is an upper bound (<=), "
                    "so allocating NOTHING is trivially optimal (objective 0, no routes). "
                    "Add a flow-forcing constraint — require each supply node to be fully "
                    "allocated (for each i: sum_j x[i,j] == supply[i]) OR each processor's "
                    "intake/demand to be met (for each j: sum_i x[i,j] >= demand[j]). "
                    "Re-formulate WITH that constraint."
                )

        return issues

    def _modify_formulation(
        self, base: OptimizationFormulation, modification: str,
    ) -> OptimizationFormulation:
        """What-if: modify existing formulation based on user request."""
        messages = [
            SystemMessage(content=(
                "You are an optimization expert. Given an existing formulation "
                "and a modification request, produce the UPDATED formulation. "
                "Change ONLY what the modification requires. Keep everything else identical."
            )),
            HumanMessage(content=(
                f"## Current Formulation\n{base.model_dump_json(indent=2)}\n\n"
                f"## Requested Modification\n{modification}\n\n"
                "Produce the complete updated OptimizationFormulation JSON."
            )),
        ]
        return self._formulate(messages)

    def resolve_structural_scenario(
        self,
        base_formulation: dict,
        instruction: str,
        user_query: str,
        perturbed_rows: list[dict],
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Re-solve a what-if that structurally edits the baseline formulation (P3).

        Applies an LLM edit to the baseline formulation (add/relax a constraint or
        bound), regenerates PuLP code, and executes it on the (already
        deterministically-perturbed) data. Returns the modified formulation, the
        regenerated code, and the parsed solution.
        """
        data_path = persist_optimization_input(perturbed_rows, session_id)
        base = OptimizationFormulation.model_validate(base_formulation)
        formulation = self._modify_formulation(base, instruction)
        data_preview = make_data_preview(perturbed_rows, max_rows=3)
        code_result = self._run_stage3(
            formulation, data_preview, user_query, data_path, session_id=session_id
        )
        output = code_result.get("last_output") or ""
        error = code_result.get("last_error")
        solution = _extract_solution_json(output) if not error else None
        return {
            "formulation": formulation,
            "code": code_result.get("last_code") or "",
            "solution": solution,
            "error": error,
        }

    def _run_stage3(
        self,
        formulation: OptimizationFormulation,
        data_preview: str,
        user_query: str,
        data_path: str = "data/cypher_results.json",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Stage 3+4: Generate code, execute, and collect results."""
        template = load_prompt("optimization_codegen.txt")
        prompt_text = (
            template
            .replace("{formulation_json}", formulation.model_dump_json(indent=2))
            .replace("{data_preview}", data_preview)
            .replace("{data_path}", data_path)
        )

        messages: list = [
            SystemMessage(content=prompt_text),
            HumanMessage(content=(
                f"User question: {user_query}\n\n"
                f"Generate PuLP code for this {formulation.problem_type} problem. "
                f"Execute it using the execute_python tool. "
                f"Print SOLUTION_JSON on a single stdout line."
            )),
        ]

        tool_map = {t.name: t for t in self.tools}
        last_code: str | None = None
        last_output: str | None = None
        last_error: str | None = None
        failed_attempts = 0
        degenerate_retries = 0

        for _ in range(6):
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)

            if not ai_msg.tool_calls:
                break

            for tc in ai_msg.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                if tool_fn:
                    with execution_session(session_id):
                        tool_result = tool_fn.invoke(tc["args"])
                else:
                    tool_result = f"Unknown tool: {tc['name']}"
                messages.append(ToolMessage(
                    content=_compact_execution_observation(tool_result),
                    tool_call_id=tc["id"],
                ))

                if tc["name"] == "execute_python":
                    last_code = tc["args"].get("code", "")
                    if isinstance(tool_result, dict):
                        last_output = tool_result.get("output")
                        last_error = tool_result.get("error")
                    else:
                        last_output = None
                        last_error = str(tool_result)

            if last_error:
                failed_attempts += 1
                if failed_attempts > MAX_RETRIES:
                    raise _PipelineExhaustedError(f"Code execution failed {failed_attempts} times")

                hint = _classify_opt_error(last_error, formulation)
                messages.append(HumanMessage(content=(
                    f"Code execution failed:\n{last_error}\n\nHint: {hint}\n\n"
                    f"Attempt {failed_attempts} of {MAX_RETRIES + 1}. Fix and retry."
                )))
            elif degenerate_retries < MAX_RETRIES and (
                _is_degenerate_output(last_output) or _is_infeasible_output(last_output)
            ):
                # Solution-level self-correction: $0/no-routes ⇒ add flow-forcing
                # constraint; infeasible ⇒ relax to a feasible demand floor. Robust
                # (triggers on the actual result, not on constraint text).
                degenerate_retries += 1
                degenerate = _is_degenerate_output(last_output)
                logger.warning("Stage 3: %s solution, injecting correction (%d)",
                               "degenerate" if degenerate else "infeasible", degenerate_retries)
                messages.append(HumanMessage(
                    content=_DEGENERATE_CORRECTION if degenerate else _INFEASIBLE_CORRECTION
                ))

        if messages[-1].type != "ai" or messages[-1].tool_calls:
            final_content = _deterministic_opt_summary(last_output, last_error)
        else:
            final_content = messages[-1].content if hasattr(messages[-1], "content") else ""
        final_content = strip_plotly_markers(final_content)

        return {
            "final_content": final_content,
            "last_code": last_code,
            "last_output": last_output,
            "last_error": last_error,
        }

    def _build_result(
        self,
        formulation: OptimizationFormulation,
        code_result: dict[str, Any],
        state: dict[str, Any],
        input_rows: list[dict] | None = None,
        input_path: str = "",
    ) -> dict[str, Any]:
        """Assemble final state update from pipeline results.

        ``input_rows`` are the rows the generated code actually read; they
        go into the baseline snapshot so scenario re-runs perturb exactly
        the solved data.
        """
        output = code_result["last_output"] or ""
        error = code_result["last_error"]

        # Parse solution from stdout
        solution = _extract_solution_json(output) if not error else None

        # Deterministic post-processing (no LLM)
        chart_specs: list[dict] = []
        geo_data: dict | None = None

        if solution:
            # Enrich coordinates from Neo4j (independent of Cypher query output)
            solution = _enrich_solution_coordinates(solution)

            sankey = _build_sankey_from_solution(solution)
            if sankey:
                chart_specs.append(sankey)

            geo = _solution_routes_to_geo(solution)
            if geo.get("features"):
                geo_data = geo

        # Also extract any PLOTLY_JSON the LLM might have printed
        llm_charts = extract_plotly_specs(output)
        chart_specs.extend(llm_charts)

        # Sanitize: strip Plotly markers from message content
        final_content = code_result["final_content"]
        final_content = strip_plotly_markers(final_content)

        result: dict[str, Any] = {
            "messages": [AIMessage(content=final_content, name=self.agent_name)],
            "optimization_model": formulation.model_dump(),
            "optimization_solution": solution,
            "optimization_error": error,
            "sender": self.agent_name,
        }

        # Persist the session baseline snapshot (formulation + cached code +
        # input data + KPIs/duals/binding) so a later what-if scenario can
        # perturb its data and re-run the cached code without re-formulating.
        if solution and not error:
            baseline_data = (
                input_rows if input_rows is not None else _collect_input_rows(state)
            )
            baseline_run = build_optimization_run(
                formulation, code_result.get("last_code") or "", solution,
                input_data=baseline_data,
                input_path=input_path,
            )
            result["optimization_baseline"] = baseline_run.model_dump()

        if chart_specs:
            result["chart_specs"] = chart_specs
        if geo_data:
            result["geo_data"] = geo_data

        # Past steps
        task_desc = state.get("worker_task", "Optimization")
        if error:
            result_summary = f"Error: {error}"
        elif solution:
            result_summary = f"Solution: {json.dumps(solution, default=str)[:500]}"
        else:
            result_summary = "(no solution)"
        result["past_steps"] = [(task_desc, result_summary)]

        # Worker feedback (quality signals)
        feedback = self._assess_solution_quality(solution, state, geo_data)
        if feedback:
            result["worker_feedback"] = feedback

        return result

    # ── Single-Shot Fallback ─────────────────────────────────────────

    def _assess_solution_quality(
        self,
        solution: dict | None,
        state: dict[str, Any],
        geo_data: dict | None,
    ) -> list[dict]:
        """Assess optimization output quality. Returns structured feedback."""
        if not solution:
            return []

        feedback = []
        cypher_results = state.get("cypher_results") or []

        # Check 0: degenerate zero-flow solution (under-constrained min-cost LP)
        status = str(solution.get("status", "")).lower()
        routes0 = solution.get("routes") or []
        obj0 = solution.get("objective")
        if status.startswith("optimal") and not routes0 and not obj0:
            feedback.append({
                "type": "degenerate_solution",
                "agent": "Optimization",
                "message": (
                    "The LP solved to objective 0 with no allocations — the model is "
                    "under-constrained (no flow-forcing constraint). Re-dispatch "
                    "optimization and require supply to be fully allocated or demand "
                    "to be met (>=/== constraint), not just upper-bound (<=) capacities."
                ),
            })

        # Check 1: Objective magnitude vs input cost total
        cost_cols = {"transport_cost", "cost", "total_cost", "shipping_cost"}
        input_total = 0.0
        for row in cypher_results:
            for col in cost_cols:
                if col in row and isinstance(row[col], (int, float)):
                    input_total += row[col]
                    break
        objective = solution.get("objective", 0)
        if input_total > 0 and abs(objective) > input_total * 100:
            ratio = abs(objective) / input_total
            feedback.append({
                "type": "implausible_result",
                "agent": "Optimization",
                "message": (
                    f"Objective (${objective:,.0f}) is {ratio:,.0f}x the input cost "
                    f"total (${input_total:,.0f}). The cost model likely multiplied "
                    f"volume by total cost instead of using per-unit cost."
                ),
            })

        # Check 2: Zero-length routes in geo_data
        if geo_data and geo_data.get("features"):
            zero_len = 0
            for feat in geo_data["features"]:
                coords = feat.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2 and coords[0] == coords[-1]:
                    zero_len += 1
            total = len(geo_data["features"])
            if zero_len > 0:
                # Collect entity names for suggested enrichment query
                entity_names = set()
                for route in solution.get("routes", []):
                    entity_names.add(route.get("from", ""))
                    entity_names.add(route.get("to", ""))
                entity_names.discard("")
                feedback.append({
                    "type": "data_gap",
                    "agent": "Optimization",
                    "message": (
                        f"{zero_len}/{total} route LineStrings have identical "
                        f"origin/dest coordinates and will be invisible on the map"
                    ),
                    "suggested_action": (
                        "Dispatch Cypher to look up coordinates: "
                        "MATCH (n) WHERE n.name IN "
                        f"{sorted(entity_names)[:10]} "
                        "AND n.lat IS NOT NULL "
                        "RETURN n.name AS name, n.lat AS lat, n.lon AS lon"
                    ),
                })

        # Check 3: Trivial solution (no reallocation)
        routes = solution.get("routes", [])
        if routes and cypher_results:
            input_count = len(cypher_results)
            sol_count = len(routes)
            if sol_count == input_count:
                input_vols = sorted(
                    r.get("volume_lbs_month", r.get("volume", 0))
                    for r in cypher_results
                )
                sol_vols = sorted(r.get("volume", 0) for r in routes)
                if input_vols == sol_vols:
                    feedback.append({
                        "type": "trivial_solution",
                        "agent": "Optimization",
                        "message": (
                            "Solution has identical routes and volumes as input data. "
                            "The LP model may lack degrees of freedom — consider "
                            "allowing all possible processor-DC pairs, not just "
                            "existing routes."
                        ),
                    })

        return feedback

    def _run_single_shot(self, state: dict[str, Any]) -> dict[str, Any]:
        """Fallback: direct code generation without structured formulation."""
        cypher_results = _collect_input_rows(state)
        data_path = persist_optimization_input(cypher_results, state.get("session_id"))
        task = state.get("worker_task") or "Formulate and solve an optimization problem."
        user_query = state.get("user_query", "")

        template = load_prompt("optimization_codegen.txt")
        data_preview = make_data_preview(cypher_results)
        system_prompt = (
            template
            .replace("{formulation_json}", f"(No structured formulation — generate from task: {task})")
            .replace("{data_preview}", data_preview)
            .replace("{data_path}", data_path)
        )

        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question: {user_query}\n\nTask: {task}\n\n"
                f"Data at {data_path} ({len(cypher_results)} rows). "
                f"Write PuLP code, execute via execute_python, print SOLUTION_JSON."
            )),
        ]

        tool_map = {t.name: t for t in self.tools}
        last_output: str | None = None
        last_error: str | None = None
        failed = 0
        degenerate_retries = 0

        for _ in range(6):
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)
            if not ai_msg.tool_calls:
                break
            for tc in ai_msg.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                if tool_fn:
                    with execution_session(state.get("session_id")):
                        tool_result = tool_fn.invoke(tc["args"])
                else:
                    tool_result = f"Unknown: {tc['name']}"
                messages.append(ToolMessage(
                    content=_compact_execution_observation(tool_result),
                    tool_call_id=tc["id"],
                ))
                if tc["name"] == "execute_python" and isinstance(tool_result, dict):
                    last_output = tool_result.get("output")
                    last_error = tool_result.get("error")
            if last_error:
                failed += 1
                if failed > MAX_RETRIES:
                    break
                messages.append(HumanMessage(content=f"Error:\n{last_error}\nFix and retry."))
            elif degenerate_retries < MAX_RETRIES and (
                _is_degenerate_output(last_output) or _is_infeasible_output(last_output)
            ):
                degenerate_retries += 1
                messages.append(HumanMessage(
                    content=_DEGENERATE_CORRECTION if _is_degenerate_output(last_output)
                    else _INFEASIBLE_CORRECTION
                ))

        if messages[-1].type != "ai" or messages[-1].tool_calls:
            final = _deterministic_opt_summary(last_output, last_error)
        else:
            final = messages[-1].content if hasattr(messages[-1], "content") else ""
        final = strip_plotly_markers(final)
        solution = _extract_solution_json(last_output or "") if not last_error else None

        chart_specs = []
        geo_data = None

        if solution:
            solution = _enrich_solution_coordinates(solution)
            sankey = _build_sankey_from_solution(solution)
            if sankey:
                chart_specs.append(sankey)
            geo = _solution_routes_to_geo(solution)
            if geo.get("features"):
                geo_data = geo

        # Extract LLM-generated Plotly charts from stdout
        if last_output:
            llm_charts = extract_plotly_specs(last_output)
            chart_specs.extend(llm_charts)

        result: dict[str, Any] = {
            "messages": [AIMessage(content=final, name=self.agent_name)],
            "optimization_model": None,
            "optimization_solution": solution,
            "optimization_error": last_error,
            "sender": self.agent_name,
            "past_steps": [(task, f"Solution: {json.dumps(solution, default=str)[:300]}" if solution else f"Error: {last_error}")],
        }
        if chart_specs:
            result["chart_specs"] = chart_specs
        if geo_data:
            result["geo_data"] = geo_data
        return result
