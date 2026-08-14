"""Chat API endpoint with SSE streaming.

Handles chat messages, invokes the LangGraph workflow, and streams
agent progress events to the frontend in real-time.

Updated for Supervisor architecture: initial state uses new fields
(next_worker, worker_task, supervisor_plan) instead of old ones
(intent, plan, current_step_index, completed_steps, response).
"""

import inspect
import logging
import uuid
from typing import AsyncGenerator, Dict, Any

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from ..core.graph import GRAPH_RECURSION_LIMIT
from ..core.state import GRASSState, TURN_RESET_STATE
from ..utils.nvl_transformer import records_to_nvl_graph
from ..utils.neo4j_serializer import to_jsonable as _to_jsonable
from .sessions import append_message, ensure_session_exists, get_effective_session_model_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# Global reference to the compiled graph (set by server.py)
_graph = None
_graph_factory = None

# Store run_id -> message mapping (in production, use Redis or database)
_active_runs: dict[str, dict] = {}
_STALE_RUN_TTL = 600  # 10 minutes


def _cleanup_stale_runs() -> None:
    """Remove runs older than TTL that were never streamed."""
    import time
    now = time.time()
    stale = [rid for rid, data in _active_runs.items()
             if now - data.get("created_at", now) > _STALE_RUN_TTL]
    for rid in stale:
        del _active_runs[rid]


def set_graph(graph):
    """Set the compiled LangGraph workflow."""
    global _graph
    _graph = graph


def set_graph_factory(factory):
    """Set a session-aware graph factory."""
    global _graph_factory
    _graph_factory = factory


async def _resolve_graph(session_id: str):
    """Return the graph instance to use for a session."""
    if _graph_factory is not None:
        graph = _graph_factory(session_id)
        if inspect.isawaitable(graph):
            return await graph
        return graph
    return _graph


# -- Pydantic models ---------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    region_bbox: str | None = None
    # "direct" (default react loop) or "plan" (cooperative planning gate).
    mode: str | None = None


class ChatResponse(BaseModel):
    run_id: str
    session_id: str


class PlanDecisionRequest(BaseModel):
    run_id: str
    decision: str                       # "accept" / "approve" / "run" → accept; else revise
    steps: list[dict[str, Any]] | None = None  # edited plan steps (optional)
    content: str | None = None          # free-text feedback for a revise/replan


# -- SSE event builders -------------------------------------------------------


def build_sse_event(event_type: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Build an SSE event dict for EventSourceResponse."""
    import json
    return {
        "event": event_type,
        "data": json.dumps(_to_jsonable(data)),
    }


# -- progress-ledger SSE helpers ---------------------------------------------

_LEDGER_PHASE_BY_ROUTE = {
    "dispatch": "executing",
    "loop": "executing",
    "replan": "replanning",
    "finalize": "finalizing",
}


def _enabled_plan_steps(plan_steps: list[dict] | None) -> list[dict]:
    """Return the steps the user left enabled (the executable subset)."""
    if not plan_steps:
        return []
    return [s for s in plan_steps if s.get("enabled", True) is not False]


def _build_ledger_progress(output: dict, plan_steps: list[dict] | None) -> dict | None:
    """Build a ``progress`` payload from one Executor turn's state delta.

    Maps the ledger's ``current_step_idx`` + ``plan_route`` onto a per-step
    checklist (done / running / pending) plus the running progress summary,
    so the frontend can render a live execution timeline.
    """
    enabled = _enabled_plan_steps(plan_steps)
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


def _final_ledger_progress(plan_steps: list[dict] | None) -> dict | None:
    """All-steps-complete snapshot emitted when the Finalize node closes."""
    enabled = _enabled_plan_steps(plan_steps)
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


async def _get_pending_interrupt(graph, config) -> Any | None:
    """Return the pending co-planning interrupt payload for a thread, or None.

    When the graph pauses at the PlanGate (``interrupt()``), the payload is
    exposed on the persisted state's pending tasks, not on the event stream.
    """
    if not hasattr(graph, "aget_state"):
        return None
    snapshot = await graph.aget_state(config)
    for task in getattr(snapshot, "tasks", ()) or ():
        for intr in getattr(task, "interrupts", ()) or ():
            return getattr(intr, "value", intr)
    return None


async def _emit_graph_events(
    graph,
    graph_input,
    run_id: str,
    session_id: str,
    config: dict,
) -> AsyncGenerator[Dict[str, str], None]:
    """Run the graph for ``graph_input`` and emit SSE events.

    Shared by the initial stream (input = initial state) and the resume
    stream (input = ``Command(resume=...)``). If the graph pauses at the
    plan gate, emits ``plan`` + ``plan_pending`` and returns WITHOUT a
    ``done`` event, keeping the run alive for a plan decision.
    """
    step_counter = 0
    active_step_ids: dict[str, str] = {}
    final_response_markdown: str | None = None
    collected_chart_specs: list[dict] = []
    collected_geo_data: dict | None = None
    # Plan steps for the ledger progress timeline (captured from the planner
    # nodes; backfilled from persisted state if the plan predates this stream).
    ledger_plan_steps: list[dict] | None = None

    async for event in graph.astream_events(graph_input, config=config, version="v2"):
        event_type = event.get("event")
        name = event.get("name", "")
        data = event.get("data", {})

        # -- co-planning nodes: capture the plan + stream ledger progress ---
        if event_type == "on_chain_end" and name in ("Planner", "PlanGate", "Replan"):
            plan_obj = (data.get("output", {}) or {}).get("plan")
            if isinstance(plan_obj, dict) and plan_obj.get("steps"):
                ledger_plan_steps = plan_obj["steps"]
            continue

        if event_type == "on_chain_end" and name == "Executor":
            output = data.get("output", {}) or {}
            if ledger_plan_steps is None and hasattr(graph, "aget_state"):
                snapshot = await graph.aget_state(config)
                values = getattr(snapshot, "values", {}) or {}
                plan_obj = values.get("plan")
                if isinstance(plan_obj, dict):
                    ledger_plan_steps = plan_obj.get("steps")
            progress = _build_ledger_progress(output, ledger_plan_steps)
            if progress is not None:
                yield build_sse_event("progress", progress)
            continue

        if event_type == "on_chain_end" and name == "Finalize":
            output = data.get("output", {}) or {}
            response_md = output.get("response_markdown")
            if response_md:
                final_response_markdown = response_md
                yield build_sse_event("response", {"markdown": response_md})
            final_progress = _final_ledger_progress(ledger_plan_steps)
            if final_progress is not None:
                yield build_sse_event("progress", final_progress)
            continue

        if event_type == "on_chain_start" and name in [
            "Supervisor", "Cypher", "Analytics", "Optimization", "Report", "ScenarioRunner"
        ]:
            step_counter += 1
            step_id = f"{run_id}:{step_counter}"
            active_step_ids[name] = step_id
            yield build_sse_event("agent_start", {
                "agent": name, "status": "running", "step_id": step_id,
            })

        elif event_type == "on_chain_end" and name in [
            "Supervisor", "Cypher", "Analytics", "Optimization", "Report", "ScenarioRunner"
        ]:
            output = data.get("output", {})
            step_id = active_step_ids.pop(name, None)

            if name == "Supervisor":
                plan = output.get("supervisor_plan")
                if plan:
                    yield build_sse_event("plan", {
                        "intent": plan.get("intent", ""),
                        "summary": plan.get("summary", ""),
                        "steps": plan.get("steps", []),
                        "requires_geo": plan.get("requires_geo", False),
                        "requires_optimization": plan.get("requires_optimization", False),
                    })
                response_md = output.get("response_markdown")
                if response_md:
                    final_response_markdown = response_md
                    yield build_sse_event("response", {"markdown": response_md})
                geo_data = output.get("geo_data")
                if geo_data and geo_data.get("features"):
                    collected_geo_data = geo_data
                    yield build_sse_event("geo_data", {"geojson": geo_data})

            elif name == "Cypher":
                cypher_query = output.get("cypher_query")
                cypher_results = output.get("cypher_results") or []
                if cypher_query:
                    columns = list(cypher_results[0].keys()) if cypher_results else []
                    graph_payload = records_to_nvl_graph(cypher_results)
                    yield build_sse_event("cypher_query", {
                        "query": cypher_query,
                        "results": cypher_results,
                        "columns": columns,
                        "graph": graph_payload,
                        "graph_truncated": graph_payload.get("stats", {}).get("truncated", False),
                        "graph_warnings": graph_payload.get("warnings", []),
                    })

            elif name == "Analytics":
                analysis_results = output.get("analysis_results")
                if analysis_results:
                    yield build_sse_event("analysis", {
                        "summary": "Analysis complete", "results": analysis_results,
                    })
                chart_specs = output.get("chart_specs") or []
                for i, spec in enumerate(chart_specs):
                    chart_id = str(uuid.uuid4())
                    collected_chart_specs.append({"id": chart_id, "index": i, "spec": spec})
                    yield build_sse_event("chart_spec", {"id": chart_id, "index": i, "spec": spec})

            elif name == "Optimization":
                opt_solution = output.get("optimization_solution")
                if opt_solution:
                    yield build_sse_event("optimization", {
                        "model": str(output.get("optimization_model", "")),
                        "solution": opt_solution,
                        "status": opt_solution.get("status", "unknown") if isinstance(opt_solution, dict) else "unknown",
                    })
                opt_charts = output.get("chart_specs") or []
                for i, spec in enumerate(opt_charts):
                    chart_id = str(uuid.uuid4())
                    collected_chart_specs.append({"id": chart_id, "index": i, "spec": spec})
                    yield build_sse_event("chart_spec", {"id": chart_id, "index": i, "spec": spec})
                opt_geo = output.get("geo_data")
                if opt_geo and opt_geo.get("features"):
                    collected_geo_data = opt_geo
                    yield build_sse_event("geo_data", {"geojson": opt_geo})

            elif name == "Report":
                report_file = output.get("report_file")
                if report_file:
                    file_id = report_file.split("/")[-1] if "/" in report_file else report_file
                    yield build_sse_event("report", {
                        "url": f"/api/files/{file_id}", "title": "Supply Chain Report",
                    })

            elif name == "ScenarioRunner":
                comparison = output.get("scenario_comparison")
                if comparison:
                    yield build_sse_event("scenario_comparison", comparison)
                sc_charts = output.get("chart_specs") or []
                for i, spec in enumerate(sc_charts):
                    chart_id = str(uuid.uuid4())
                    collected_chart_specs.append({"id": chart_id, "index": i, "spec": spec})
                    yield build_sse_event("chart_spec", {"id": chart_id, "index": i, "spec": spec})
                sc_geo = output.get("geo_data")
                if sc_geo and sc_geo.get("features"):
                    collected_geo_data = sc_geo
                    yield build_sse_event("geo_data", {"geojson": sc_geo})

            yield build_sse_event("agent_complete", {
                "agent": name, "status": "done", "step_id": step_id, "result": {},
            })

        elif event_type == "on_chain_error":
            error_msg = str(data.get("error", "Unknown error"))
            step_id = active_step_ids.pop(name, None)
            yield build_sse_event("error", {
                "agent": name, "step_id": step_id, "error": error_msg,
            })

    # -- co-planning pause: graph stopped at the plan gate --------------
    pending = await _get_pending_interrupt(graph, config)
    if pending is not None:
        payload = pending if isinstance(pending, dict) else {"plan_str": str(pending)}
        yield build_sse_event("plan_review", {
            "run_id": run_id,
            "plan": payload.get("plan"),
            "plan_str": payload.get("plan_str", ""),
            "summary": payload.get("summary", ""),
            "message": payload.get("message", ""),
        })
        yield build_sse_event("plan_pending", {"run_id": run_id})
        run_data = _active_runs.get(run_id)
        if run_data is not None:
            run_data["awaiting_plan"] = True
        return

    # -- normal completion ---------------------------------------------
    if final_response_markdown is None and hasattr(graph, "aget_state"):
        state_snapshot = await graph.aget_state(config)
        values = getattr(state_snapshot, "values", {}) or {}
        response_md = values.get("response_markdown")
        if isinstance(response_md, str) and response_md:
            final_response_markdown = response_md

    if final_response_markdown:
        msg_metadata: dict | None = None
        if collected_chart_specs or collected_geo_data:
            msg_metadata = {}
            if collected_chart_specs:
                msg_metadata["visualizations"] = [
                    {
                        "id": cs["id"],
                        "type": "chart",
                        "title": (
                            cs["spec"].get("layout", {}).get("title", {}).get("text")
                            if isinstance(cs["spec"].get("layout", {}).get("title"), dict)
                            else cs["spec"].get("layout", {}).get("title")
                        ),
                        "data": cs["spec"],
                    }
                    for cs in collected_chart_specs
                ]
            if collected_geo_data:
                msg_metadata["geo_data"] = collected_geo_data
        await append_message(
            session_id, role="assistant", content=final_response_markdown,
            run_id=run_id, metadata=msg_metadata,
        )

    yield build_sse_event("done", {})
    if run_id in _active_runs:
        del _active_runs[run_id]



# -- Main chat endpoint -------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def create_chat(body: ChatRequest):
    """Initiate a chat run and return run_id for SSE streaming."""
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if not _graph and not _graph_factory:
        raise HTTPException(status_code=500, detail="LangGraph not initialized")

    run_id = str(uuid.uuid4())
    session = await ensure_session_exists(body.session_id)
    session_id = session["id"]
    await append_message(
        session_id,
        role="user",
        content=body.message,
        run_id=run_id,
    )

    import time as _time
    _cleanup_stale_runs()
    _active_runs[run_id] = {
        "session_id": session_id,
        "message": body.message,
        "region_bbox": body.region_bbox,
        "mode": body.mode or "direct",
        "stream_started": False,
        "created_at": _time.time(),
    }

    logger.info("Created chat run %s for session %s", run_id, session_id)

    return ChatResponse(
        run_id=run_id,
        session_id=session_id,
    )


_ACCEPT_DECISIONS = {"accept", "accepted", "approve", "approved", "run", "execute", "yes", "ok"}


@router.post("/chat/plan-decision")
async def submit_plan_decision(body: PlanDecisionRequest):
    """Resume a paused co-planning run with the human's decision.

    Builds the ``HumanInputFormat`` resume payload (accept / edit / revise),
    resumes the graph via ``Command(resume=...)``, and streams the
    continuation (which may pause again at the gate after a replan).
    """
    run_data = _active_runs.get(body.run_id)
    if not run_data:
        raise HTTPException(
            status_code=404, detail="Run not found or no longer awaiting a plan decision"
        )

    session_id = run_data["session_id"]
    accepted = body.decision.strip().lower() in _ACCEPT_DECISIONS
    resume_value: dict[str, Any] = {"accepted": accepted, "content": body.content or ""}
    if body.steps:
        # Edited plan from the frontend; Plan.from_obj accepts agent/agent_name.
        resume_value["plan"] = {"steps": body.steps}

    run_data["awaiting_plan"] = False
    logger.info(
        "Resuming run %s with plan decision: accepted=%s, edited=%s",
        body.run_id, accepted, bool(body.steps),
    )

    async def resume_generator() -> AsyncGenerator[Dict[str, str], None]:
        try:
            graph = await _resolve_graph(session_id)
            if graph is None:
                raise RuntimeError("LangGraph not initialized")
            config = {
                "configurable": {"thread_id": session_id},
                "recursion_limit": GRAPH_RECURSION_LIMIT,
            }
            async for event in _emit_graph_events(
                graph, Command(resume=resume_value), body.run_id, session_id, config
            ):
                yield event
        except Exception as e:  # noqa: BLE001 - surface to client
            logger.error("Resume error for run %s: %s", body.run_id, e, exc_info=True)
            yield build_sse_event("error", {"agent": "System", "error": str(e)})
            yield build_sse_event("done", {})
            if body.run_id in _active_runs:
                del _active_runs[body.run_id]

    return EventSourceResponse(resume_generator())


@router.get("/stream/{run_id}")
async def stream_chat(run_id: str):
    """Stream agent progress events via SSE."""

    run_data = _active_runs.get(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Run not found")
    if run_data.get("stream_started"):
        raise HTTPException(status_code=409, detail="Run is already streaming")

    run_data["stream_started"] = True

    user_message = run_data["message"]
    region_bbox = run_data.get("region_bbox")
    session_id = run_data["session_id"]
    if region_bbox:
        user_message_with_region = (
            f"{user_message}\n\n"
            f"Region focus (bbox sw_lat,sw_lng,ne_lat,ne_lng): [{region_bbox}]. "
            "Prioritize analysis within this region unless user asks otherwise."
        )
    else:
        user_message_with_region = user_message

    async def event_generator() -> AsyncGenerator[Dict[str, str], None]:
        """Generate SSE events from LangGraph execution."""

        try:
            from langchain_core.messages import HumanMessage
            graph = await _resolve_graph(session_id)
            if graph is None:
                raise RuntimeError("LangGraph not initialized")

            # Emit effective model config so frontend can confirm which models are active
            try:
                effective_config = await get_effective_session_model_config(session_id)
                yield build_sse_event("config_applied", {
                    "agent_models": effective_config.get("agent_models", {}),
                })
            except Exception:
                pass  # Non-critical — don't block chat if config lookup fails

            # Initial state — per-turn transients are reset centrally via
            # TURN_RESET_STATE (src/core/state.py) so checkpointed values from
            # the previous turn cannot leak into this one.
            initial_state: GRASSState = {
                **TURN_RESET_STATE,
                "messages": [HumanMessage(content=user_message_with_region)],
                "user_query": user_message_with_region,
                "region_bbox": region_bbox,
                "session_id": session_id,
                # Co-planning mode (default "direct")
                "mode": run_data.get("mode", "direct"),
            }

            config = {
                "configurable": {"thread_id": session_id},
                "recursion_limit": GRAPH_RECURSION_LIMIT,
            }
            async for event in _emit_graph_events(
                graph, initial_state, run_id, session_id, config
            ):
                yield event

        except Exception as e:
            logger.error(f"Stream error for run {run_id}: {e}", exc_info=True)
            await append_message(
                session_id,
                role="assistant",
                content=f"Error: {e}",
                run_id=run_id,
            )
            yield build_sse_event("error", {
                "agent": "System",
                "error": str(e),
            })
            yield build_sse_event("done", {})

            # Clean up on error
            if run_id in _active_runs:
                del _active_runs[run_id]

    return EventSourceResponse(event_generator())
