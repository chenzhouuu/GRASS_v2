"""GRASS shared state definition.

All agents read from and write to this TypedDict.  The ``messages``
field uses LangGraph's ``add_messages`` reducer so messages accumulate
rather than being replaced.  ``past_steps`` uses ``operator.add`` so
each worker appends (task, result) tuples.

Supervisor refactor (2026-03-08):
  Removed: intent, plan, current_step_index, completed_steps, response
  Added:   next_worker, worker_task, supervisor_plan

Co-planning mode (2026-06-06):
  Added:   mode, in_planning_mode, plan, plan_str, n_replans, plan_route,
           replan_feedback. NOTE: ``plan`` here is the NEW co-planning
           artifact (Plan.model_dump(), a Magentic-UI port), not the old
           Plan/Process/Replanner DAG that was removed above.
"""

import operator
from typing import Any, List, Optional, Tuple, Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GRASSState(TypedDict):
    # -- message history ------------------------------------------------
    messages: Annotated[List[BaseMessage], add_messages]

    # -- user query -----------------------------------------------------
    user_query: str
    region_bbox: Optional[str]
    # Session identity, set per-request by the API. Workers use it to derive
    # the per-session data-file path (data/outputs/<session>/...), isolating
    # concurrent sessions from each other.
    session_id: Optional[str]

    # -- Supervisor control (replaces intent, plan, current_step_index,
    #    completed_steps, response) --------------------------------------
    next_worker: Optional[str]           # routing signal for supervisor_router
    worker_task: Optional[str]           # task description for dispatched worker
    supervisor_plan: Optional[dict]      # plan from generate_plan tool (optional, legacy)
    requires_geo: bool
    requires_optimization: bool

    # -- Co-planning mode (Magentic-UI co-planning port) -----------------
    # ``mode``: "direct" = react loop only (default, == today's behavior);
    #           "plan"   = cooperative planning with a human approval gate.
    mode: Optional[str]
    in_planning_mode: Optional[bool]     # planning phase vs execution phase
    plan: Optional[dict]                 # approved/proposed Plan.model_dump()
    plan_str: Optional[str]              # rendered plan text (Magentic plan_str)
    n_replans: Optional[int]             # bounded replan counter
    plan_route: Optional[str]            # transient router signal: gate/replan/execute/end
    replan_feedback: Optional[str]       # human feedback carried into a replan

    # -- Progress-ledger executor (Step 4) -------------------------------
    # ``execution_engine``: "ledger" after a plan is approved in plan mode;
    # workers then return to the Executor instead of the Supervisor.
    execution_engine: Optional[str]
    current_step_idx: Optional[int]      # index into ENABLED plan steps
    n_rounds: Optional[int]              # ledger-turn counter (vs max_turns)
    information_collected: Optional[str] # accumulated progress summaries
    # Stall detection: signature of the worker results at the last ledger turn
    # and how many consecutive dispatch turns have produced no new results.
    last_progress_signature: Optional[str]
    stall_rounds: Optional[int]

    # -- Evaluation (kept from Replanner) --------------------------------
    past_steps: Annotated[List[Tuple[str, str]], operator.add]

    # -- Worker feedback (append-only quality signals) --------------------
    worker_feedback: Annotated[List[dict], operator.add]

    # -- Cypher Agent output --------------------------------------------
    cypher_query: Optional[str]
    cypher_results: Optional[List[dict]]
    cypher_error: Optional[str]
    cypher_metadata: Optional[dict]

    # -- Accumulated query results (append-only across multiple Cypher calls)
    # Legacy data source for the Optimization Agent when no session
    # workspace exists (benchmarks, tests). Workspace sessions keep rows in
    # named tables on disk instead (src/tools/session_workspace.py) and
    # leave this empty, so checkpoints stay bounded (P2-c).
    all_query_results: Annotated[List[dict], operator.add]

    # -- Analytics Agent output (analysis) --------------------------------
    analysis_code: Optional[str]
    analysis_results: Optional[Any]
    analysis_error: Optional[str]

    # -- Analytics Agent output (charts + geo) --------------------------
    chart_specs: Optional[List[dict]]   # Plotly JSON specs for frontend
    geo_data: Optional[dict]            # GeoJSON FeatureCollection for Leaflet

    # -- Optimization Agent output --------------------------------------
    optimization_model: Optional[dict]  # OptimizationFormulation.model_dump()
    optimization_solution: Optional[dict]
    optimization_error: Optional[str]

    # -- What-if scenario engine (P0) -----------------------------------
    # Durable snapshot of the last successful structured optimization run
    # (OptimizationRun.model_dump()): formulation + cached code + KPIs +
    # duals + binding constraints. A later scenario perturbs this baseline's
    # data and re-runs its cached code. One baseline per session.
    optimization_baseline: Optional[dict]
    # Scenario the Supervisor/Planner asked the ScenarioRunner to run
    # (Scenario.model_dump()); consumed by the ScenarioRunner.
    pending_scenario: Optional[dict]
    # One-factor sensitivity sweep request: {"factors": [{name,target,low,high,selector?}]}.
    # Consumed by ScenarioRunner.run_sweep → tornado chart.
    pending_sweep: Optional[dict]
    # Accumulated scenario run snapshots (OptimizationRun.model_dump()).
    scenario_runs: Annotated[List[dict], operator.add]
    # Latest baseline-vs-scenario comparison (ScenarioComparison.model_dump()):
    # KPI deltas + binding shift + objective waterfall + narrative. Drives the
    # frontend ScenarioComparisonCard.
    scenario_comparison: Optional[dict]

    # -- Report Agent output --------------------------------------------
    report_file: Optional[str]

    # -- Response output (set by Supervisor directly) --------------------
    response_markdown: Optional[str]

    # -- Metadata -------------------------------------------------------
    sender: Optional[str]


# Per-turn transient fields and their reset values, merged into the initial
# state of every user turn (src/api/chat.py). The checkpointer preserves the
# previous turn's value for any key omitted from the initial state, so every
# per-turn transient field MUST appear here — a field added to GRASSState but
# not listed here (or exempted below) leaks across turns. That was the
# ledger-routing bug fixed 2026-08-14: a stale ``execution_engine`` routed
# direct-mode workers into the plan executor, and a stale ``pending_scenario``
# re-ran the previous what-if. ``tests/test_state.py`` enforces that every
# GRASSState field is classified either here or in TURN_DURABLE_FIELDS.
TURN_RESET_STATE: dict = {
    # Supervisor control
    "next_worker": None,
    "worker_task": None,
    "supervisor_plan": None,
    "requires_geo": False,
    "requires_optimization": False,
    # Co-planning
    "in_planning_mode": None,
    "plan": None,
    "plan_str": None,
    "n_replans": 0,
    "plan_route": None,
    "replan_feedback": None,
    # Progress-ledger executor
    "execution_engine": None,
    "current_step_idx": 0,
    "n_rounds": 0,
    "information_collected": None,
    "last_progress_signature": None,
    "stall_rounds": 0,
    # Cypher outputs
    "cypher_query": None,
    "cypher_results": None,
    "cypher_error": None,
    "cypher_metadata": None,
    # Analytics outputs
    "analysis_code": None,
    "analysis_results": None,
    "analysis_error": None,
    "chart_specs": None,
    "geo_data": None,
    # Optimization outputs
    "optimization_model": None,
    "optimization_solution": None,
    "optimization_error": None,
    # Scenario engine (the baseline itself is durable, see below)
    "pending_scenario": None,
    "pending_sweep": None,
    "scenario_comparison": None,
    # Report + response
    "report_file": None,
    "response_markdown": None,
    "sender": None,
}

# GRASSState fields deliberately NOT reset each turn:
#   - messages / user_query / region_bbox / mode: set per-request by the API.
#   - optimization_baseline: session-durable by design — one baseline per
#     session, later what-ifs perturb it.
#   - past_steps / worker_feedback / all_query_results / scenario_runs:
#     append-only reducers; an initial [] appends nothing, so they persist
#     for the session's lifetime.
TURN_DURABLE_FIELDS = frozenset({
    "messages", "user_query", "region_bbox", "mode", "session_id",
    "optimization_baseline",
    "past_steps", "worker_feedback", "all_query_results", "scenario_runs",
})
