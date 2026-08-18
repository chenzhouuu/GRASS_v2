"""Chat API endpoint with SSE streaming.

Backend-owned runs: POST /api/chat starts the graph in a background task that
runs to completion whether or not any client is connected. Events flow through
the vendored Aegra broker (live fan-out + replay buffer); GET /api/stream is a
pure reader that can attach late, reattach with ``Last-Event-ID``, or be opened
from several clients at once.
"""

import asyncio
import contextlib
import inspect
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Dict, Any

from fastapi import APIRouter, Header, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from ..core.events import GRASSEvent
from ..core.graph import GRAPH_RECURSION_LIMIT
from ..core.state import GRASSState, TURN_RESET_STATE
from ..db import runs as run_store
from ..utils.neo4j_serializer import to_jsonable as _to_jsonable
from .sessions import append_message, ensure_session_exists, get_effective_session_model_config
from .vendor.aegra_broker import (
    active_runs,
    broker_manager,
    extract_event_sequence,
    generate_event_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# Global reference to the compiled graph (set by server.py)
_graph = None
_graph_factory = None

# Per-run request context the broker does not carry (session binding, plan-gate
# flag). Event and replay lifetime is owned by the broker manager; entries here
# are swept once the manager has dropped the corresponding broker.
_run_meta: dict[str, dict] = {}


# A run paused at the plan gate keeps its broker open on purpose (the
# decision's continuation lands in the same stream). If no decision ever
# comes, expire it so the broker + replay buffer don't live forever.
_PAUSED_RUN_TTL_SECONDS = 3600


async def _set_run_status_quiet(run_id: str, status: str, *, error: str | None = None) -> None:
    """Best-effort status write: a DB hiccup must never take the run down."""
    try:
        await run_store.set_run_status(run_id, status, error=error)
    except Exception:
        logger.warning("Run %s: status %r not persisted", run_id, status, exc_info=True)


async def _sweep_run_meta() -> None:
    """Expire abandoned plan-gate pauses; drop metadata for reclaimed brokers."""
    now = time.time()
    for rid, meta in list(_run_meta.items()):
        if (
            meta.get("awaiting_plan")
            and now - meta.get("paused_at", now) > _PAUSED_RUN_TTL_SECONDS
        ):
            logger.info("Expiring abandoned plan-gate run %s", rid)
            meta["awaiting_plan"] = False
            await _set_run_status_quiet(
                rid, "stopped", error="plan decision never arrived (TTL)"
            )
            broker = broker_manager.get_broker(rid)
            if broker is not None:
                broker.mark_finished()  # manager's cleanup loop reclaims it
    for rid in [rid for rid in _run_meta if broker_manager.get_broker(rid) is None]:
        del _run_meta[rid]


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
    return {
        "event": event_type,
        "data": json.dumps(_to_jsonable(data)),
    }


def _last_agent_text(messages: list) -> str | None:
    """Text of the current turn's most recent assistant message, or None.

    ``messages`` is session-durable; the scan is sliced to after the last
    HumanMessage so a turn that produced no text of its own cannot
    re-deliver a previous turn's answer as the reply to a new question.
    """
    last_human = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human = i
            break
    for msg in reversed(messages[last_human + 1:]):
        if isinstance(msg, AIMessage) and isinstance(msg.content, str) and msg.content.strip():
            return msg.content
    return None


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
    """Run the graph for ``graph_input`` and forward the events its nodes emit.

    Nodes publish their own events through ``get_stream_writer()``
    (``src/core/graph.py``), which arrive here as ``stream_mode="custom"``.
    This function adds only what a node cannot know: the per-agent ``step_id``
    the frontend correlates on, and the accumulators used to persist the
    assistant message.

    Shared by the initial run (input = initial state) and the resume run
    (input = ``Command(resume=...)``). If the graph pauses at the plan gate,
    emits ``plan_review`` + ``plan_pending`` and returns WITHOUT a ``done``
    event, keeping the run alive for a plan decision.
    """
    # Step ids must be monotonic per RUN, not per segment: a plan-decision
    # resume re-enters this generator, and restarting at 1 would reuse ids
    # the frontend already correlated cards on.
    meta = _run_meta.setdefault(run_id, {})
    active_step_ids: dict[str, str] = {}
    final_response_markdown: str | None = None
    collected_chart_specs: list[dict] = []
    collected_geo_data: dict | None = None

    async for _mode, chunk in graph.astream(
        graph_input, config=config, stream_mode=["custom"]
    ):
        name = chunk.get("event")
        payload = dict(chunk.get("data") or {})
        agent = payload.get("agent")

        if name == GRASSEvent.AGENT_START.value:
            meta["step_counter"] = meta.get("step_counter", 0) + 1
            step_id = f"{run_id}:{meta['step_counter']}"
            active_step_ids[agent] = step_id
            payload["step_id"] = step_id
        elif name in (GRASSEvent.AGENT_COMPLETE.value, GRASSEvent.ERROR.value):
            payload["step_id"] = active_step_ids.pop(agent, None)
        elif name == GRASSEvent.RESPONSE.value:
            final_response_markdown = payload.get("markdown")
        elif name == GRASSEvent.CHART_SPEC.value:
            collected_chart_specs.append(payload)
        elif name == GRASSEvent.GEO_DATA.value:
            collected_geo_data = payload.get("geojson")

        yield build_sse_event(name, payload)

    # -- co-planning pause: graph stopped at the plan gate --------------
    pending = await _get_pending_interrupt(graph, config)
    if pending is not None:
        payload = pending if isinstance(pending, dict) else {"plan_str": str(pending)}
        # State first, announcement last: anyone reacting to ``plan_pending``
        # (plan-decision POST, sweep, active-run discovery) must already see
        # the paused state when the event reaches them. ``segment_paused`` is
        # the driver's private copy of this segment's outcome — a fast
        # decision can flip ``awaiting_plan`` back before the driver's own
        # check runs, and the driver must still not close the broker.
        meta["awaiting_plan"] = True
        meta["segment_paused"] = True
        meta["paused_at"] = time.time()
        yield build_sse_event("plan_review", {
            "run_id": run_id,
            "plan": payload.get("plan"),
            "plan_str": payload.get("plan_str", ""),
            "summary": payload.get("summary", ""),
            "message": payload.get("message", ""),
        })
        yield build_sse_event("plan_pending", {"run_id": run_id})
        return

    # -- normal completion ---------------------------------------------
    if final_response_markdown is None and hasattr(graph, "aget_state"):
        state_snapshot = await graph.aget_state(config)
        values = getattr(state_snapshot, "values", {}) or {}
        response_md = values.get("response_markdown")
        if isinstance(response_md, str) and response_md:
            final_response_markdown = response_md
        else:
            # A react run can end at a terminal worker (Report -> END) with the
            # Supervisor never writing the final answer. Fall back to the last
            # agent message so the run still delivers and persists a reply.
            final_response_markdown = _last_agent_text(values.get("messages") or [])
            if final_response_markdown:
                yield build_sse_event("response", {"markdown": final_response_markdown})

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
        # Flag BEFORE the await: the DB commit happens inside the await, so a
        # cancellation "during" the await can land after the row is written —
        # the flag keeps _persist_partial_response from appending it twice.
        # A genuine write failure rolls the flag back so the fallback still runs.
        meta["persisted"] = True
        try:
            await append_message(
                session_id, role="assistant", content=final_response_markdown,
                run_id=run_id, metadata=msg_metadata,
            )
        except asyncio.CancelledError:
            raise  # commit may still have landed; keep the flag
        except Exception:
            meta["persisted"] = False
            raise

    yield build_sse_event("done", {})


# -- Startup recovery ---------------------------------------------------------


async def startup_run_recovery() -> None:
    """Reconcile the runs table with reality after a process (re)start.

    A run whose status is non-terminal here died with the previous process
    life: mark it failed, and salvage what its event stream already carried —
    a published ``response`` becomes the persisted answer; otherwise an error
    message tells the user why there is no reply. Also drops run events past
    the 7-day retention window.
    """
    orphans = await run_store.find_orphan_runs()
    for run in orphans:
        salvaged: str | None = None
        for _seq, event_name, data in reversed(
            await run_store.load_run_events(run.id)
        ):
            if event_name == GRASSEvent.RESPONSE.value:
                try:
                    salvaged = json.loads(data).get("markdown")
                except (json.JSONDecodeError, AttributeError):
                    pass
                break
        await run_store.set_run_status(run.id, "failed", error="backend restarted")
        if not await run_store.has_assistant_message(run.id):
            await append_message(
                run.session_id,
                role="assistant",
                content=salvaged
                or "Error: the backend restarted while this run was in "
                "progress. Please send your question again.",
                run_id=run.id,
            )
        logger.info(
            "Orphaned run %s marked failed (salvaged response: %s)",
            run.id,
            bool(salvaged),
        )

    expired = await run_store.delete_expired_run_events()
    if orphans or expired:
        logger.info(
            "Run recovery: %d orphan(s) failed, %d expired event(s) dropped",
            len(orphans),
            expired,
        )


# -- Background run driver ----------------------------------------------------


async def _persist_partial_response(graph, config, session_id: str, run_id: str) -> None:
    """Persist whatever answer the checkpoint already holds.

    Read from the checkpoint, not from generator locals — those die with the
    cancelled task.
    """
    if graph is None or not hasattr(graph, "aget_state"):
        return
    if _run_meta.get(run_id, {}).get("persisted"):
        return  # the normal completion path already wrote this answer
    snapshot = await graph.aget_state(config)
    response_md = (getattr(snapshot, "values", {}) or {}).get("response_markdown")
    if isinstance(response_md, str) and response_md:
        await append_message(
            session_id, role="assistant", content=response_md, run_id=run_id
        )


async def _drive_run(run_id: str, session_id: str, graph_input) -> None:
    """Own a run start-to-finish, independent of any connected client.

    Forwards every SSE event to the run's broker (live fan-out + replay
    buffer). Assistant persistence happens inside ``_emit_graph_events``, so
    it too is client-independent. On cancellation, persists what the
    checkpoint already holds and re-raises.
    """
    broker = broker_manager.get_or_create_broker(run_id)

    async def publish(event: Dict[str, str]) -> None:
        event_id = await broker_manager.allocate_event_id(run_id)
        await broker.put(event_id, event)
        # Write-through: the durable copy replay reads after a broker is gone
        # (process restart, reclaimed broker). A failed write must not take
        # the run down — live viewers are unaffected.
        try:
            await run_store.record_run_event(
                run_id,
                extract_event_sequence(event_id),
                event.get("event", ""),
                event.get("data", ""),
            )
        except Exception:
            logger.warning(
                "Run %s: event %s not persisted", run_id, event_id, exc_info=True
            )

    graph = None
    config = {
        "configurable": {"thread_id": session_id},
        "recursion_limit": GRAPH_RECURSION_LIMIT,
    }
    try:
        graph = await _resolve_graph(session_id)
        if graph is None:
            raise RuntimeError("LangGraph not initialized")

        if not isinstance(graph_input, Command):
            # Fresh run: tell viewers which model config is active.
            try:
                effective_config = await get_effective_session_model_config(session_id)
                await publish(build_sse_event("config_applied", {
                    "agent_models": effective_config.get("agent_models", {}),
                }))
            except Exception:
                pass  # Non-critical — don't block chat if config lookup fails

        async for event in _emit_graph_events(
            graph, graph_input, run_id, session_id, config
        ):
            await publish(event)
    except asyncio.CancelledError:
        # mark_finished must run even if the awaits below are themselves
        # cancelled (loop shutdown), or the broker is never reclaimed.
        try:
            with contextlib.suppress(Exception):
                await _persist_partial_response(graph, config, session_id, run_id)
            with contextlib.suppress(Exception):
                await publish(build_sse_event("done", {}))
            await _set_run_status_quiet(run_id, "stopped")
        finally:
            broker.mark_finished()
        raise
    except Exception as e:
        logger.error("Run %s failed: %s", run_id, e, exc_info=True)
        with contextlib.suppress(Exception):
            await append_message(
                session_id, role="assistant", content=f"Error: {e}", run_id=run_id
            )
        await publish(build_sse_event("error", {"agent": "System", "error": str(e)}))
        await publish(build_sse_event("done", {}))
        await _set_run_status_quiet(run_id, "failed", error=str(e))
        broker.mark_finished()
        return

    meta = _run_meta.get(run_id)
    if meta is not None and meta.pop("segment_paused", False):
        # This segment ended at the plan gate: the broker stays open so the
        # decision's continuation lands in the same stream. Skip the status
        # write if a decision already resumed the run in the meantime.
        if meta.get("awaiting_plan"):
            await _set_run_status_quiet(run_id, "awaiting_plan")
        return
    await _set_run_status_quiet(run_id, "completed")
    broker.mark_finished()


def _start_run_task(run_id: str, session_id: str, graph_input) -> None:
    """Spawn the background driver and register it for cancellation."""
    task = asyncio.create_task(_drive_run(run_id, session_id, graph_input))
    active_runs[run_id] = task

    def _clear(finished: asyncio.Task, run_id: str = run_id) -> None:
        if active_runs.get(run_id) is finished:
            del active_runs[run_id]

    task.add_done_callback(_clear)


async def _broker_events(
    run_id: str, last_event_id: str | None
) -> AsyncGenerator[Dict[str, str], None]:
    """Follow a run's broker from a cursor; frames carry ``id:`` for reconnect.

    The vendored ``aiter()`` replays the whole buffer to every new subscriber
    and callers dedup by event id (upstream contract) — the sequence filter
    here is that dedup, and it also implements ``Last-Event-ID``. A
    ``plan_pending`` event closes the view: the run is paused for a human
    decision, and the continuation is watched via the plan-decision response.
    """
    broker = broker_manager.get_broker(run_id)
    cursor = extract_event_sequence(last_event_id) if last_event_id else 0
    if broker is None:
        # The broker died with the previous process life (or was reclaimed):
        # replay the durable copy. The run itself is over — no live tail.
        for seq, event_name, data in await run_store.load_run_events(
            run_id, after_seq=cursor
        ):
            yield {
                "event": event_name,
                "data": data,
                "id": generate_event_id(run_id, seq),
            }
        return
    async for event_id, event in broker.aiter():
        if extract_event_sequence(event_id) <= cursor:
            continue
        yield {**event, "id": event_id}
        if event.get("event") == "plan_pending":
            return


# -- Main chat endpoint -------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def create_chat(body: ChatRequest):
    """Start a chat run owned by the backend.

    The graph executes in a background task and runs to completion whether or
    not any client watches; ``GET /api/stream/{run_id}`` only observes it.
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    if not _graph and not _graph_factory:
        raise HTTPException(status_code=500, detail="LangGraph not initialized")

    run_id = str(uuid.uuid4())
    session = await ensure_session_exists(body.session_id)
    session_id = session["id"]

    # One executing run per session thread: two concurrent graph executions
    # on the same thread_id interleave checkpoint writes and each wipes the
    # other's transients via TURN_RESET_STATE. (A run paused at the plan
    # gate has no live task, so a new message is still allowed then.)
    for rid, meta in list(_run_meta.items()):
        if meta.get("session_id") != session_id:
            continue
        task = active_runs.get(rid)
        if task is not None and not task.done():
            raise HTTPException(
                status_code=409,
                detail=f"Session already has a run in progress ({rid}); "
                "wait for it to finish.",
            )

    await append_message(
        session_id,
        role="user",
        content=body.message,
        run_id=run_id,
    )

    if body.region_bbox:
        user_message_with_region = (
            f"{body.message}\n\n"
            f"Region focus (bbox sw_lat,sw_lng,ne_lat,ne_lng): [{body.region_bbox}]. "
            "Prioritize analysis within this region unless user asks otherwise."
        )
    else:
        user_message_with_region = body.message

    # Initial state — per-turn transients are reset centrally via
    # TURN_RESET_STATE (src/core/state.py) so checkpointed values from
    # the previous turn cannot leak into this one.
    initial_state: GRASSState = {
        **TURN_RESET_STATE,
        "messages": [HumanMessage(content=user_message_with_region)],
        "user_query": user_message_with_region,
        "region_bbox": body.region_bbox,
        "session_id": session_id,
        # Co-planning mode (default "direct")
        "mode": body.mode or "direct",
    }

    await _sweep_run_meta()
    await run_store.create_run(run_id, session_id)
    _run_meta[run_id] = {"session_id": session_id, "awaiting_plan": False}
    broker_manager.get_or_create_broker(run_id)
    _start_run_task(run_id, session_id, initial_state)

    logger.info("Created chat run %s for session %s", run_id, session_id)

    return ChatResponse(
        run_id=run_id,
        session_id=session_id,
    )


_ACCEPT_DECISIONS = {"accept", "accepted", "approve", "approved", "run", "execute", "yes", "ok"}


@router.post("/chat/plan-decision")
async def submit_plan_decision(body: PlanDecisionRequest):
    """Resume a paused co-planning run with the human's decision.

    Builds the ``HumanInputFormat`` resume payload (accept / edit / revise) and
    resumes the graph via ``Command(resume=...)`` in a background task on the
    run's existing broker. The response is a view of the continuation from the
    current cursor (which may pause again at the gate after a replan).
    """
    meta = _run_meta.get(body.run_id)
    if not meta or not meta.get("awaiting_plan"):
        raise HTTPException(
            status_code=404, detail="Run not found or no longer awaiting a plan decision"
        )

    session_id = meta["session_id"]
    accepted = body.decision.strip().lower() in _ACCEPT_DECISIONS
    resume_value: dict[str, Any] = {"accepted": accepted, "content": body.content or ""}
    if body.steps:
        # Edited plan from the frontend; Plan.from_obj accepts agent/agent_name.
        resume_value["plan"] = {"steps": body.steps}

    meta["awaiting_plan"] = False
    logger.info(
        "Resuming run %s with plan decision: accepted=%s, edited=%s",
        body.run_id, accepted, bool(body.steps),
    )

    cursor = generate_event_id(
        body.run_id, await broker_manager.get_event_sequence(body.run_id)
    )
    await _set_run_status_quiet(body.run_id, "running")
    _start_run_task(body.run_id, session_id, Command(resume=resume_value))
    return EventSourceResponse(_broker_events(body.run_id, cursor))


@router.get("/sessions/{session_id}/active-run")
async def get_active_run(session_id: str):
    """The session's live run — executing or paused at the plan gate — or null.

    Lets a client that just loaded a session discover and re-attach to a run
    it does not know about (page refresh, second tab). ``last_event_id`` is
    the current replay cursor; a fresh viewer usually omits it to get the
    full backlog.
    """
    for rid, meta in list(_run_meta.items()):
        if meta.get("session_id") != session_id:
            continue
        task = active_runs.get(rid)
        running = task is not None and not task.done()
        if not running and not meta.get("awaiting_plan"):
            continue
        return {
            "run_id": rid,
            "status": "running" if running else "awaiting_plan",
            "last_event_id": generate_event_id(
                rid, await broker_manager.get_event_sequence(rid)
            ),
        }
    return None


# Policy, not an accident: a viewer disconnecting NEVER stops a run —
# viewing is not owning. The ONLY client-initiated cancellation is the
# explicit stop endpoint below (upstream equivalent: stream.stop() vs
# disconnect() ≡ stop({cancel: false})).
DISCONNECT_STOPS_RUN = False


@router.post("/chat/{run_id}/stop")
async def stop_chat(run_id: str):
    """Cancel a backend-owned run explicitly.

    Cancellation drives ``_drive_run``'s CancelledError path: the partial
    answer already in the checkpoint is persisted, viewers get ``done``,
    and the broker is marked finished. Stopping a finished run is a no-op.
    """
    meta = _run_meta.get(run_id)
    if meta is None and broker_manager.get_broker(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if meta is not None and meta.get("awaiting_plan"):
        # Paused at the plan gate: no live task — abandoning it just
        # closes out the broker.
        meta["awaiting_plan"] = False
        await _set_run_status_quiet(run_id, "stopped")
        broker = broker_manager.get_broker(run_id)
        if broker is not None:
            broker.mark_finished()
        logger.info("Stopped plan-paused run %s", run_id)
        return {"run_id": run_id, "status": "stopped"}

    task = active_runs.get(run_id)
    if task is None or task.done():
        return {"run_id": run_id, "status": "already_finished"}

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    logger.info("Stopped run %s by request", run_id)
    return {"run_id": run_id, "status": "stopped"}


@router.get("/stream/{run_id}")
async def stream_chat(
    run_id: str,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """Watch a run. A pure reader: attach late, reattach with a cursor, open
    several at once — none of it affects the run itself."""
    if broker_manager.get_broker(run_id) is None:
        # No live broker — still serve the durable record if the run existed
        # (finished long ago, or died with a previous process life).
        if await run_store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")

    async def _on_client_close(message: Dict[str, Any]) -> None:
        logger.info("Viewer for run %s disconnected; run continues", run_id)

    return EventSourceResponse(
        _broker_events(run_id, last_event_id),
        client_close_handler_callable=_on_client_close,
    )
