"""Chat API endpoint with SSE streaming.

Handles chat messages, invokes the LangGraph workflow, and streams
agent progress events to the frontend in real-time.

Updated for Supervisor architecture: initial state uses new fields
(next_worker, worker_task, supervisor_plan) instead of old ones
(intent, plan, current_step_index, completed_steps, response).
"""

import asyncio
import inspect
import logging
import uuid
from typing import AsyncGenerator, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from ..core.state import GRASSState
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


class ChatResponse(BaseModel):
    run_id: str
    session_id: str


class PlanDecisionRequest(BaseModel):
    run_id: str
    decision: str
    steps: list[dict[str, Any]] | None = None


# -- SSE event builders -------------------------------------------------------


def build_sse_event(event_type: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Build an SSE event dict for EventSourceResponse."""
    import json
    return {
        "event": event_type,
        "data": json.dumps(_to_jsonable(data)),
    }



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
        "stream_started": False,
        "created_at": _time.time(),
    }

    logger.info("Created chat run %s for session %s", run_id, session_id)

    return ChatResponse(
        run_id=run_id,
        session_id=session_id,
    )


@router.post("/chat/plan-decision")
async def submit_plan_decision(body: PlanDecisionRequest):
    """Accept frontend plan decisions for compatibility with the UI flow."""
    run_data = _active_runs.get(body.run_id)
    if run_data is not None:
        run_data["plan_decision"] = body.decision
        run_data["plan_steps"] = body.steps or []
        logger.info(
            "Received plan decision for run %s: %s", body.run_id, body.decision
        )

    return {
        "ok": True,
        "run_id": body.run_id,
        "decision": body.decision,
    }


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

            # Initial state — Supervisor architecture
            initial_state: GRASSState = {
                "messages": [HumanMessage(content=user_message_with_region)],
                "user_query": user_message_with_region,
                "region_bbox": region_bbox,
                # Supervisor control
                "next_worker": None,
                "worker_task": None,
                "supervisor_plan": None,
                "requires_geo": False,
                "requires_optimization": False,
                # Evaluation
                "past_steps": [],
                # Worker feedback
                "worker_feedback": [],
                # Worker outputs
                "cypher_query": None,
                "cypher_results": None,
                "cypher_error": None,
                "cypher_metadata": None,
                "all_query_results": [],
                "analysis_code": None,
                "analysis_results": None,
                "analysis_error": None,
                "chart_specs": None,
                "geo_data": None,
                "optimization_model": None,
                "optimization_solution": None,
                "optimization_error": None,
                "report_file": None,
                "response_markdown": None,
                "sender": None,
            }

            step_counter = 0
            active_step_ids: dict[str, str] = {}
            final_response_markdown: str | None = None
            # Collect artifacts for persistence alongside the assistant message
            collected_chart_specs: list[dict] = []
            collected_geo_data: dict | None = None

            # Stream events from LangGraph (thread_id enables multi-turn)
            async for event in graph.astream_events(
                initial_state,
                config={"configurable": {"thread_id": session_id}},
                version="v2",
            ):
                event_type = event.get("event")
                name = event.get("name", "")
                data = event.get("data", {})

                # Node start events
                if event_type == "on_chain_start" and name in [
                    "Supervisor", "Cypher", "Analytics",
                    "Optimization", "Report"
                ]:
                    step_counter += 1
                    step_id = f"{run_id}:{step_counter}"
                    active_step_ids[name] = step_id
                    yield build_sse_event("agent_start", {
                        "agent": name,
                        "status": "running",
                        "step_id": step_id,
                    })

                # Node completion events
                elif event_type == "on_chain_end" and name in [
                    "Supervisor", "Cypher", "Analytics",
                    "Optimization", "Report"
                ]:
                    output = data.get("output", {})
                    step_id = active_step_ids.pop(name, None)

                    # Supervisor completion
                    if name == "Supervisor":
                        # Emit plan if generated
                        plan = output.get("supervisor_plan")
                        if plan:
                            yield build_sse_event("plan", {
                                "intent": plan.get("intent", ""),
                                "summary": plan.get("summary", ""),
                                "steps": plan.get("steps", []),
                                "requires_geo": plan.get("requires_geo", False),
                                "requires_optimization": plan.get("requires_optimization", False),
                            })

                        # Emit response if Supervisor produced final answer
                        response_md = output.get("response_markdown")
                        if response_md:
                            final_response_markdown = response_md
                            yield build_sse_event("response", {
                                "markdown": response_md,
                            })

                        # Emit geo data if Supervisor extracted it
                        geo_data = output.get("geo_data")
                        if geo_data and geo_data.get("features"):
                            collected_geo_data = geo_data
                            yield build_sse_event("geo_data", {
                                "geojson": geo_data,
                            })

                    # Cypher Agent
                    elif name == "Cypher":
                        cypher_query = output.get("cypher_query")
                        cypher_results = output.get("cypher_results") or []

                        if cypher_query:
                            columns = list(cypher_results[0].keys()) if cypher_results else []

                            yield build_sse_event("cypher_query", {
                                "query": cypher_query,
                                "results": cypher_results,
                                "columns": columns,
                            })

                    # Analytics Agent (replaces Code + Visualization)
                    elif name == "Analytics":
                        # Emit analysis results
                        analysis_results = output.get("analysis_results")
                        if analysis_results:
                            yield build_sse_event("analysis", {
                                "summary": "Analysis complete",
                                "results": analysis_results,
                            })

                        # Emit chart specs (Plotly JSON)
                        chart_specs = output.get("chart_specs") or []
                        for i, spec in enumerate(chart_specs):
                            chart_id = str(uuid.uuid4())
                            collected_chart_specs.append({
                                "id": chart_id, "index": i, "spec": spec,
                            })
                            yield build_sse_event("chart_spec", {
                                "id": chart_id,
                                "index": i,
                                "spec": spec,
                            })

                    # Optimization Agent
                    elif name == "Optimization":
                        opt_solution = output.get("optimization_solution")
                        if opt_solution:
                            yield build_sse_event("optimization", {
                                "model": str(output.get("optimization_model", "")),
                                "solution": opt_solution,
                                "status": opt_solution.get("status", "unknown") if isinstance(opt_solution, dict) else "unknown",
                            })

                        # Charts (deterministic Sankey + any LLM-generated)
                        opt_charts = output.get("chart_specs") or []
                        for i, spec in enumerate(opt_charts):
                            chart_id = str(uuid.uuid4())
                            collected_chart_specs.append({"id": chart_id, "index": i, "spec": spec})
                            yield build_sse_event("chart_spec", {
                                "id": chart_id, "index": i, "spec": spec,
                            })

                        # Geo data (route LineStrings from solution)
                        opt_geo = output.get("geo_data")
                        if opt_geo and opt_geo.get("features"):
                            collected_geo_data = opt_geo
                            yield build_sse_event("geo_data", {"geojson": opt_geo})

                    # Report Agent
                    elif name == "Report":
                        report_file = output.get("report_file")
                        if report_file:
                            file_id = report_file.split("/")[-1] if "/" in report_file else report_file
                            yield build_sse_event("report", {
                                "url": f"/api/files/{file_id}",
                                "title": "Supply Chain Report",
                            })

                    # Agent complete
                    yield build_sse_event("agent_complete", {
                        "agent": name,
                        "status": "done",
                        "step_id": step_id,
                        "result": {},
                    })

                # Error events
                elif event_type == "on_chain_error":
                    error_msg = str(data.get("error", "Unknown error"))
                    step_id = active_step_ids.pop(name, None)
                    yield build_sse_event("error", {
                        "agent": name,
                        "step_id": step_id,
                        "error": error_msg,
                    })

            if final_response_markdown is None and hasattr(graph, "aget_state"):
                state_snapshot = await graph.aget_state(
                    {"configurable": {"thread_id": session_id}}
                )
                values = getattr(state_snapshot, "values", {}) or {}
                response_md = values.get("response_markdown")
                if isinstance(response_md, str) and response_md:
                    final_response_markdown = response_md

            if final_response_markdown:
                # Build metadata with artifacts for cross-refresh persistence
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
                    session_id,
                    role="assistant",
                    content=final_response_markdown,
                    run_id=run_id,
                    metadata=msg_metadata,
                )

            # Final done event
            yield build_sse_event("done", {})

            # Clean up
            if run_id in _active_runs:
                del _active_runs[run_id]

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
