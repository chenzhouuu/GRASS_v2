"""GRASS shared state definition.

All agents read from and write to this TypedDict.  The ``messages``
field uses LangGraph's ``add_messages`` reducer so messages accumulate
rather than being replaced.  ``past_steps`` uses ``operator.add`` so
each worker appends (task, result) tuples.

Supervisor refactor (2026-03-08):
  Removed: intent, plan, current_step_index, completed_steps, response
  Added:   next_worker, worker_task, supervisor_plan
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

    # -- Supervisor control (replaces intent, plan, current_step_index,
    #    completed_steps, response) --------------------------------------
    next_worker: Optional[str]           # routing signal for supervisor_router
    worker_task: Optional[str]           # task description for dispatched worker
    supervisor_plan: Optional[dict]      # plan from generate_plan tool (optional)
    requires_geo: bool
    requires_optimization: bool

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
    # Used by Optimization Agent to access data from ALL Cypher steps,
    # not just the last one (which overwrites cypher_results).
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

    # -- Report Agent output --------------------------------------------
    report_file: Optional[str]

    # -- Response output (set by Supervisor directly) --------------------
    response_markdown: Optional[str]

    # -- Metadata -------------------------------------------------------
    sender: Optional[str]
