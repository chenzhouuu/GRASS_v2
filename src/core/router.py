"""Routing functions for the GRASS LangGraph workflow.

Single router replaces the previous three (plan_router, process_router,
replan_router).  The Supervisor sets ``next_worker`` in state; the router
reads it and returns the destination node name.
"""

import logging

from langgraph.graph import END

from .state import GRASSState

logger = logging.getLogger(__name__)

VALID_WORKERS = {"Cypher", "Analytics", "Optimization", "Report"}


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
