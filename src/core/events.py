"""SSE event vocabulary and the node-output → event mapping.

The frontend consumes a fixed set of named events.  Until now those names lived
as bare string literals inside ``src/api/chat.py``, which reconstructed them by
matching LangGraph's internal ``astream_events`` records against node names and
state fields.  That coupled the API layer to LangGraph's event schema.

Here the names are declared once, and :func:`node_events` turns a node's state
update into the events it implies.  Nodes emit the result through
``get_stream_writer()``, which reaches the caller via ``stream_mode="custom"`` —
the channel LangGraph Server and Aegra both use for user-defined data.
"""

import uuid
from enum import Enum
from typing import Any, Iterator

from ..utils.nvl_transformer import records_to_nvl_graph


class GRASSEvent(str, Enum):
    """Every SSE event name the frontend knows how to dispatch."""

    # Run lifecycle
    CONFIG_APPLIED = "config_applied"
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    ERROR = "error"
    DONE = "done"

    # Planning
    PLAN = "plan"
    PLAN_REVIEW = "plan_review"
    PLAN_PENDING = "plan_pending"
    PROGRESS = "progress"

    # Worker output
    RESPONSE = "response"
    CYPHER_QUERY = "cypher_query"
    ANALYSIS = "analysis"
    CHART_SPEC = "chart_spec"
    OPTIMIZATION = "optimization"
    GEO_DATA = "geo_data"
    REPORT = "report"
    SCENARIO_COMPARISON = "scenario_comparison"


NodeEvent = tuple[str, dict]

REPORT_TITLE = "Supply Chain Report"


def _chart_events(output: dict) -> Iterator[NodeEvent]:
    """One ``chart_spec`` event per spec, each with its own id."""
    for index, spec in enumerate(output.get("chart_specs") or []):
        yield GRASSEvent.CHART_SPEC.value, {
            "id": str(uuid.uuid4()),
            "index": index,
            "spec": spec,
        }


def _geo_event(output: dict) -> Iterator[NodeEvent]:
    """A ``geo_data`` event, but only when there is geometry to draw."""
    geo_data = output.get("geo_data")
    if geo_data and geo_data.get("features"):
        yield GRASSEvent.GEO_DATA.value, {"geojson": geo_data}


def _supervisor_events(output: dict) -> Iterator[NodeEvent]:
    plan = output.get("supervisor_plan")
    if plan:
        yield GRASSEvent.PLAN.value, {
            "intent": plan.get("intent", ""),
            "summary": plan.get("summary", ""),
            "steps": plan.get("steps", []),
            "requires_geo": plan.get("requires_geo", False),
            "requires_optimization": plan.get("requires_optimization", False),
        }
    response_markdown = output.get("response_markdown")
    if response_markdown:
        yield GRASSEvent.RESPONSE.value, {"markdown": response_markdown}
    yield from _geo_event(output)


def _cypher_events(output: dict) -> Iterator[NodeEvent]:
    query = output.get("cypher_query")
    if not query:
        return
    results = output.get("cypher_results") or []
    graph = records_to_nvl_graph(results)
    yield GRASSEvent.CYPHER_QUERY.value, {
        "query": query,
        "results": results,
        "columns": list(results[0].keys()) if results else [],
        "graph": graph,
        "graph_truncated": graph.get("stats", {}).get("truncated", False),
        "graph_warnings": graph.get("warnings", []),
    }


def _analytics_events(output: dict) -> Iterator[NodeEvent]:
    analysis_results = output.get("analysis_results")
    if analysis_results:
        yield GRASSEvent.ANALYSIS.value, {
            "summary": "Analysis complete",
            "results": analysis_results,
        }
    yield from _chart_events(output)


def _optimization_events(output: dict) -> Iterator[NodeEvent]:
    solution = output.get("optimization_solution")
    if solution:
        yield GRASSEvent.OPTIMIZATION.value, {
            "model": str(output.get("optimization_model", "")),
            "solution": solution,
            "status": solution.get("status", "unknown") if isinstance(solution, dict) else "unknown",
        }
    yield from _chart_events(output)
    yield from _geo_event(output)


def _report_events(output: dict) -> Iterator[NodeEvent]:
    report_file = output.get("report_file")
    if not report_file:
        return
    file_id = report_file.split("/")[-1] if "/" in report_file else report_file
    yield GRASSEvent.REPORT.value, {
        "url": f"/api/files/{file_id}",
        "title": REPORT_TITLE,
    }


def _scenario_events(output: dict) -> Iterator[NodeEvent]:
    comparison = output.get("scenario_comparison")
    if comparison:
        yield GRASSEvent.SCENARIO_COMPARISON.value, comparison
    yield from _chart_events(output)
    yield from _geo_event(output)


_BY_NODE = {
    "Supervisor": _supervisor_events,
    "Cypher": _cypher_events,
    "Analytics": _analytics_events,
    "Optimization": _optimization_events,
    "Report": _report_events,
    "ScenarioRunner": _scenario_events,
}


def node_events(node_name: str, output: dict[str, Any] | None) -> list[NodeEvent]:
    """Return the ``(event_name, payload)`` pairs a node's state update implies.

    Pure: the only impurity is the ``uuid4()`` identifying each chart spec, which
    the frontend uses to de-duplicate charts across re-renders.
    """
    builder = _BY_NODE.get(node_name)
    if builder is None or not output:
        return []
    return list(builder(output))


# -- progress ledger (plan mode) ---------------------------------------------

_LEDGER_PHASE_BY_ROUTE = {
    "dispatch": "executing",
    "loop": "executing",
    "replan": "replanning",
    "finalize": "finalizing",
}


def enabled_plan_steps(plan_steps: list[dict] | None) -> list[dict]:
    """Return the steps the user left enabled (the executable subset)."""
    if not plan_steps:
        return []
    return [s for s in plan_steps if s.get("enabled", True) is not False]


def build_ledger_progress(output: dict, plan_steps: list[dict] | None) -> dict | None:
    """Build a ``progress`` payload from one Executor turn's state delta.

    Maps the ledger's ``current_step_idx`` + ``plan_route`` onto a per-step
    checklist (done / running / pending) plus the running progress summary, so
    the frontend can render a live execution timeline.
    """
    enabled = enabled_plan_steps(plan_steps)
    if not enabled:
        return None

    route = output.get("plan_route")
    idx = output.get("current_step_idx")
    idx = 0 if idx is None else int(idx)
    total = len(enabled)
    phase = _LEDGER_PHASE_BY_ROUTE.get(route, "executing")
    finalizing = phase == "finalizing"

    steps: list[dict] = []
    for i, step in enumerate(enabled):
        if finalizing or i < idx:
            status = "done"
        elif i == idx:
            status = "running"
        else:
            status = "pending"
        steps.append({
            "index": i + 1,
            "title": step.get("title", ""),
            "agent": step.get("agent", ""),
            "status": status,
        })

    # The running summary accumulates as "\n- line"; surface the latest line.
    raw_summary = (output.get("information_collected") or "").strip()
    current_summary = ""
    if raw_summary:
        current_summary = raw_summary.splitlines()[-1].lstrip("- ").strip()

    return {
        "phase": phase,
        "current_step": min(idx + 1, total),
        "total_steps": total,
        "summary": current_summary,
        "steps": steps,
    }


def final_ledger_progress(plan_steps: list[dict] | None) -> dict | None:
    """All-steps-complete snapshot emitted when the Finalize node closes."""
    enabled = enabled_plan_steps(plan_steps)
    if not enabled:
        return None
    return {
        "phase": "complete",
        "current_step": len(enabled),
        "total_steps": len(enabled),
        "summary": "",
        "steps": [
            {
                "index": i + 1,
                "title": s.get("title", ""),
                "agent": s.get("agent", ""),
                "status": "done",
            }
            for i, s in enumerate(enabled)
        ],
    }


def _plan_steps(state: dict, output: dict) -> list[dict] | None:
    """The plan's steps, whichever of state or this turn's delta carries them."""
    plan = output.get("plan") or state.get("plan") or {}
    return plan.get("steps") if isinstance(plan, dict) else None


def executor_events(state: dict, output: dict | None) -> list[NodeEvent]:
    """The live execution timeline, one snapshot per Executor turn."""
    if not output:
        return []
    progress = build_ledger_progress(output, _plan_steps(state, output))
    return [(GRASSEvent.PROGRESS.value, progress)] if progress else []


def finalize_events(state: dict, output: dict | None) -> list[NodeEvent]:
    """The final answer, plus the all-done timeline snapshot."""
    if not output:
        return []
    events: list[NodeEvent] = []
    response_markdown = output.get("response_markdown")
    if response_markdown:
        events.append((GRASSEvent.RESPONSE.value, {"markdown": response_markdown}))
    progress = final_ledger_progress(_plan_steps(state, output))
    if progress:
        events.append((GRASSEvent.PROGRESS.value, progress))
    return events
