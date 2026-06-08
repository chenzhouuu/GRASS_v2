"""Routing functions for the GRASS LangGraph workflow.

Single router replaces the previous three (plan_router, process_router,
replan_router).  The Supervisor sets ``next_worker`` in state; the router
reads it and returns the destination node name.
"""

import logging

from langgraph.graph import END

from .state import GRASSState

logger = logging.getLogger(__name__)

VALID_WORKERS = {"Cypher", "Analytics", "Optimization", "Report", "ScenarioRunner"}


def supervisor_router(state: GRASSState) -> str:
    """Route based on the Supervisor's ``next_worker`` field.

    Returns
    -------
    str
        One of the worker node names, or ``END`` when ``next_worker``
        is ``None`` (Supervisor produced the final response directly).
    """
    next_worker = state.get("next_worker")

    if next_worker in VALID_WORKERS:
        logger.info("supervisor_router -> %s", next_worker)
        return next_worker

    # next_worker is None → Supervisor responded directly
    logger.info("supervisor_router -> END (Supervisor responded directly)")
    return END


# ── Co-planning routers (only used when a Planner is wired) ───────────


def entry_router(state: GRASSState) -> str:
    """Route the graph entry by ``mode``.

    Returns ``"plan"`` for cooperative planning, else ``"direct"`` (the
    default react-only behavior).
    """
    if state.get("mode") == "plan":
        logger.info("entry_router -> plan (co-planning)")
        return "plan"
    return "direct"


def plan_draft_router(state: GRASSState) -> str:
    """After the Planner drafts: ``"gate"`` for human review, else ``"end"``."""
    route = state.get("plan_route")
    return "gate" if route == "gate" else "end"


def plan_gate_router(state: GRASSState) -> str:
    """After the human gate: ``"execute"`` (accepted) or ``"replan"`` (rejected)."""
    route = state.get("plan_route")
    return "replan" if route == "replan" else "execute"


# ── Progress-ledger executor routers (Step 4) ────────────────────────

_EXECUTOR_WORKERS = {"Cypher", "Analytics", "Optimization", "Report", "ScenarioRunner"}


def executor_router(state: GRASSState) -> str:
    """Route from the Executor by ``plan_route``.

    - ``"dispatch"`` → the named worker (``next_worker``)
    - ``"loop"``     → back to the Executor (step completed, re-evaluate)
    - ``"replan"``   → Replan (re-gates via PlanGate)
    - anything else  → Finalize
    """
    route = state.get("plan_route")
    if route == "dispatch":
        worker = state.get("next_worker")
        if worker in _EXECUTOR_WORKERS:
            return worker
        logger.warning("executor_router: invalid dispatch worker %r -> Finalize", worker)
        return "Finalize"
    if route == "loop":
        return "Executor"
    if route == "replan":
        return "Replan"
    return "Finalize"


def worker_return_router(state: GRASSState) -> str:
    """Where a worker returns: the ledger Executor (plan mode) or the Supervisor."""
    return "Executor" if state.get("execution_engine") == "ledger" else "Supervisor"


def report_return_router(state: GRASSState) -> str:
    """Report returns to the Executor in ledger mode, else terminates (END)."""
    return "Executor" if state.get("execution_engine") == "ledger" else END
