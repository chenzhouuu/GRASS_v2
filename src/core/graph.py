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
from .router import (
    supervisor_router,
    entry_router,
    plan_draft_router,
    plan_gate_router,
    executor_router,
    worker_return_router,
    report_return_router,
)
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
    planner_agent=None,
    executor_agent=None,
    scenario_runner=None,
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

    # -- what-if scenario runner (only when wired) --------------------
    # Dormant until the Supervisor/Planner can dispatch to it (P4); when
    # absent, the graph is unchanged.
    scenario_enabled = scenario_runner is not None
    if scenario_enabled:
        workflow.add_node("ScenarioRunner", _wrap_agent(scenario_runner, "ScenarioRunner"))

    # -- co-planning nodes (only when a Planner is wired) -------------
    # When absent, the graph is identical to the react-only architecture
    # (START -> Supervisor), so existing behavior and tests are unchanged.
    if planner_agent is not None:
        workflow.add_node("Planner", planner_agent.draft_node)
        workflow.add_node("PlanGate", planner_agent.gate_node)
        workflow.add_node("Replan", planner_agent.replan_node)

    # Ledger execution requires BOTH a planner (the gate) and an executor.
    ledger_enabled = planner_agent is not None and executor_agent is not None
    if ledger_enabled:
        workflow.add_node("Executor", executor_agent.ledger_node)
        workflow.add_node("Finalize", executor_agent.finalize_node)

    # -- edges --------------------------------------------------------
    # Entry
    if planner_agent is not None:
        # mode == "plan" -> Planner; else -> Supervisor (direct react).
        workflow.add_conditional_edges(START, entry_router, {
            "plan": "Planner",
            "direct": "Supervisor",
        })
        # Planner draft -> human gate, or END (no plan / direct answer).
        workflow.add_conditional_edges("Planner", plan_draft_router, {
            "gate": "PlanGate",
            "end": END,
        })
        # Human gate -> execute (accepted) or replan (rejected). In ledger mode
        # an accepted plan runs through the progress-ledger Executor; otherwise
        # it falls back to the Supervisor react loop (Steps 1-3 behavior).
        workflow.add_conditional_edges("PlanGate", plan_gate_router, {
            "execute": "Executor" if ledger_enabled else "Supervisor",
            "replan": "Replan",
        })
        # Replan -> back to the gate.
        workflow.add_edge("Replan", "PlanGate")
    else:
        workflow.add_edge(START, "Supervisor")

    # -- progress-ledger executor edges -------------------------------
    if ledger_enabled:
        executor_targets = {
            "Cypher": "Cypher",
            "Analytics": "Analytics",
            "Optimization": "Optimization",
            "Report": "Report",
            "Executor": "Executor",   # step completed -> re-evaluate next step
            "Replan": "Replan",
            "Finalize": "Finalize",
        }
        if scenario_enabled:
            executor_targets["ScenarioRunner"] = "ScenarioRunner"
        workflow.add_conditional_edges("Executor", executor_router, executor_targets)
        workflow.add_edge("Finalize", END)

    # Supervisor -> conditional routing
    supervisor_targets = {
        "Cypher": "Cypher",
        "Analytics": "Analytics",
        "Optimization": "Optimization",
        "Report": "Report",
        END: END,
    }
    if scenario_enabled:
        supervisor_targets["ScenarioRunner"] = "ScenarioRunner"
    workflow.add_conditional_edges("Supervisor", supervisor_router, supervisor_targets)

    # Workers return for evaluation. With the ledger executor wired, the
    # return target depends on execution_engine ("ledger" -> Executor, else
    # Supervisor); otherwise it is statically the Supervisor (unchanged graph).
    return_workers = ["Cypher", "Analytics", "Optimization"]
    if scenario_enabled:
        return_workers.append("ScenarioRunner")
    if ledger_enabled:
        for worker in return_workers:
            workflow.add_conditional_edges(worker, worker_return_router, {
                "Supervisor": "Supervisor",
                "Executor": "Executor",
            })
        # Report: terminal in react mode (END), a normal step in ledger mode.
        workflow.add_conditional_edges("Report", report_return_router, {
            "Executor": "Executor",
            END: END,
        })
    else:
        for worker in return_workers:
            workflow.add_edge(worker, "Supervisor")
        workflow.add_edge("Report", END)

    return workflow.compile(checkpointer=checkpointer or MemorySaver())
