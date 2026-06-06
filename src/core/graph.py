"""GRASS LangGraph workflow construction.

Builds the Supervisor-based agent graph:
  START -> Supervisor <-> Workers -> Supervisor -> Report/END

The Supervisor replaces Plan + Process + Replanner + Response agents.
"""

import logging
from typing import Any, Callable

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from .state import GRASSState
from .router import supervisor_router
from ..utils.tracing import configure_tracing

logger = logging.getLogger(__name__)


# -- stub node factory -----------------------------------------------

def _make_stub(name: str) -> Callable[[GRASSState], dict[str, Any]]:
    """Return a pass-through node that logs and returns a placeholder."""

    def stub(state: GRASSState) -> dict[str, Any]:
        logger.info("STUB node: %s (not yet implemented)", name)
        return {
            "messages": [
                AIMessage(
                    content=f"[{name} agent not yet implemented]",
                    name=name,
                )
            ],
            "sender": name,
        }

    stub.__name__ = f"stub_{name}"
    return stub


# -- node wrappers ----------------------------------------------------

def _wrap_agent(agent, name: str) -> Callable[[GRASSState], dict[str, Any]]:
    """Wrap an agent's invoke() into a LangGraph node function."""

    def node_fn(state: GRASSState) -> dict[str, Any]:
        logger.info("Running node: %s", name)
        return agent.invoke(state)

    node_fn.__name__ = f"node_{name}"
    return node_fn


# -- graph builder ----------------------------------------------------

def build_graph(
    supervisor_agent=None,
    cypher_agent=None,
    analytics_agent=None,
    optimization_agent=None,
    report_agent=None,
    checkpointer=None,
    *,
    tracing: bool | None = None,
    langsmith_project: str | None = None,
):
    """Construct and compile the GRASS workflow graph.

    Pass real agent instances for implemented agents; the rest default
    to stubs so the graph always compiles.

    Parameters
    ----------
    tracing : bool | None
        Explicitly enable / disable LangSmith tracing.
    langsmith_project : str | None
        Override the LangSmith project name (default: ``"grass"``).
    """
    configure_tracing(enabled=tracing, project_name=langsmith_project)
    workflow = StateGraph(GRASSState)

    # -- register nodes (5 total) -------------------------------------
    workflow.add_node(
        "Supervisor",
        _wrap_agent(supervisor_agent, "Supervisor") if supervisor_agent else _make_stub("Supervisor"),
    )
    workflow.add_node(
        "Cypher",
        _wrap_agent(cypher_agent, "Cypher") if cypher_agent else _make_stub("Cypher"),
    )
    workflow.add_node(
        "Analytics",
        _wrap_agent(analytics_agent, "Analytics") if analytics_agent else _make_stub("Analytics"),
    )
    workflow.add_node(
        "Optimization",
        _wrap_agent(optimization_agent, "Optimization") if optimization_agent else _make_stub("Optimization"),
    )
    workflow.add_node(
        "Report",
        _wrap_agent(report_agent, "Report") if report_agent else _make_stub("Report"),
    )

    # -- edges --------------------------------------------------------
    # Entry
    workflow.add_edge(START, "Supervisor")

    # Supervisor -> conditional routing
    workflow.add_conditional_edges("Supervisor", supervisor_router, {
        "Cypher": "Cypher",
        "Analytics": "Analytics",
        "Optimization": "Optimization",
        "Report": "Report",
        END: END,
    })

    # Workers -> Supervisor (return for evaluation)
    for worker in ["Cypher", "Analytics", "Optimization"]:
        workflow.add_edge(worker, "Supervisor")

    # Terminal: Report -> END
    workflow.add_edge("Report", END)

    return workflow.compile(checkpointer=checkpointer or MemorySaver())
