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
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import ValidationError

from ..core.schemas import OptimizationFormulation
from ..tools.python_executor import execute_python, persist_cypher_results
from ..utils.data_summarizer import summarize_data, format_summary_for_prompt, make_data_preview
from ..utils.prompt_loader import load_prompt
from ..utils.plotly_markers import extract_plotly_specs, strip_plotly_markers

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_FORMULATION_RETRIES = 2
_MODIFY_PREFIX = "MODIFY_PREVIOUS:"

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
                    f"rgba(22, 163, 74, 0.35)"  # semi-transparent green
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
    for section in ("sets", "parameters", "variables"):
        items = d.get(section)
        if isinstance(items, dict):
            for key, val in items.items():
                if isinstance(val, dict):
                    # description → definition
                    if "definition" not in val and "description" in val:
                        val["definition"] = val.pop("description")
                    val.setdefault("definition", key)
                    # sets need size_from
                    if section == "sets":
                        val.setdefault("size_from", val.get("source_value", "unknown"))
                    # parameters need source_type + source_value
                    if section == "parameters":
                        val.setdefault("source_type", "estimated")
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
        # Prefer accumulated results (from all Cypher steps) over latest-only
        cypher_results = state.get("all_query_results") or state.get("cypher_results") or []
        persist_cypher_results(cypher_results)
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
        code_result = self._run_stage3(formulation, data_preview, user_query)

        # ── Stage 4: Post-process ────────────────────────────────
        return self._build_result(formulation, code_result, state)

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
                    f"Validation found issues:\n" + "\n".join(f"- {i}" for i in issues) +
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

    def _run_stage3(
        self, formulation: OptimizationFormulation, data_preview: str, user_query: str,
    ) -> dict[str, Any]:
        """Stage 3+4: Generate code, execute, and collect results."""
        template = load_prompt("optimization_codegen.txt")
        prompt_text = (
            template
            .replace("{formulation_json}", formulation.model_dump_json(indent=2))
            .replace("{data_preview}", data_preview)
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

        for _ in range(6):
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)

            if not ai_msg.tool_calls:
                break

            for tc in ai_msg.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                tool_result = tool_fn.invoke(tc["args"]) if tool_fn else f"Unknown tool: {tc['name']}"
                messages.append(ToolMessage(content=str(tool_result), tool_call_id=tc["id"]))

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

        # Force summary if needed
        if messages[-1].type != "ai" or messages[-1].tool_calls:
            messages.append(HumanMessage(content="Summarize the optimization results."))
            final_msg = self.model.invoke(messages)
            messages.append(final_msg)

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
    ) -> dict[str, Any]:
        """Assemble final state update from pipeline results."""
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
        cypher_results = state.get("all_query_results") or state.get("cypher_results") or []
        persist_cypher_results(cypher_results)
        task = state.get("worker_task") or "Formulate and solve an optimization problem."
        user_query = state.get("user_query", "")

        template = load_prompt("optimization_codegen.txt")
        data_preview = make_data_preview(cypher_results)
        system_prompt = (
            template
            .replace("{formulation_json}", f"(No structured formulation — generate from task: {task})")
            .replace("{data_preview}", data_preview)
        )

        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question: {user_query}\n\nTask: {task}\n\n"
                f"Data at data/cypher_results.json ({len(cypher_results)} rows). "
                f"Write PuLP code, execute via execute_python, print SOLUTION_JSON."
            )),
        ]

        tool_map = {t.name: t for t in self.tools}
        last_output: str | None = None
        last_error: str | None = None
        failed = 0

        for _ in range(6):
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)
            if not ai_msg.tool_calls:
                break
            for tc in ai_msg.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                tool_result = tool_fn.invoke(tc["args"]) if tool_fn else f"Unknown: {tc['name']}"
                messages.append(ToolMessage(content=str(tool_result), tool_call_id=tc["id"]))
                if tc["name"] == "execute_python" and isinstance(tool_result, dict):
                    last_output = tool_result.get("output")
                    last_error = tool_result.get("error")
            if last_error:
                failed += 1
                if failed > MAX_RETRIES:
                    break
                messages.append(HumanMessage(content=f"Error:\n{last_error}\nFix and retry."))

        if messages[-1].type != "ai" or messages[-1].tool_calls:
            messages.append(HumanMessage(content="Summarize the results."))
            messages.append(self.model.invoke(messages))

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
