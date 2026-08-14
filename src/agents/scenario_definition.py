"""Translate a free-text what-if request into a typed ``Scenario``.

Single source of truth for deriving structured ``Perturbation``s and
``GraphEdit``s from natural language. Used by ``ScenarioRunner`` when invoked
in plan mode (no pre-built ``pending_scenario``). Direct mode keeps building
``pending_scenario`` via the Supervisor's ``define_scenario`` tool and skips
this path.

Works with or without an optimization baseline: numeric perturbations are only
derived when a baseline exists (they reference its data columns); structural
entity outages become ``graph_edits`` and need no baseline.
"""

import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..core.schemas import GraphEdit, OptimizationRun, Perturbation, Scenario
from ..utils.data_summarizer import format_summary_for_prompt, summarize_data

logger = logging.getLogger(__name__)

_SYSTEM = """You translate a supply-chain what-if request into a structured scenario.

Two kinds of change:

1. graph_edits — a structural change to the network itself. Use for entity
   outages/closures ("Processor X goes offline", "cooperative Y shuts down"):
   emit {{op: "remove_node", label: <one of: {labels}>, name: <entity name>}}.
   If the request gives an id (e.g. P0042), put it in `id` instead of `name`.

2. perturbations — a numeric change re-solved against the optimization baseline:
- scale_param: multiply numeric column `target` by `factor` (transport cost +25% -> factor 1.25)
- set_param: set numeric column `target` to absolute `value`
- scale_capacity: scale a capacity column `target` by `factor` (plant at 2/3 -> factor 0.6667)
- remove_entity: drop rows matching `selector` (e.g. {{"processor_id": "P0042"}})
- structural: a constraint/bound change expressed in `instruction` (no numeric column)

Rules:
- An entity outage should emit a graph_edit; when a baseline exists, ALSO emit
  the matching remove_entity perturbation so the cost impact is re-solved.
- Only reference columns that appear in the baseline data schema. {no_baseline_rule}
- Prefer a unique id column in `selector` (e.g. processor_id) over a display name.
- Emit at least one change. If you cannot map the request, emit empty lists."""

_NO_BASELINE_RULE = (
    "There is NO baseline in this session: emit graph_edits only, no perturbations."
)


class _ScenarioDraft(BaseModel):
    """LLM-facing draft: name + description + typed changes (no ids)."""
    name: str = Field(default="What-if scenario", description="Short label.")
    description: str = Field(default="", description="One-line description.")
    perturbations: list[Perturbation] = Field(default_factory=list)
    graph_edits: list[GraphEdit] = Field(default_factory=list)


def scenario_from_request(
    model: Any, request_text: str, baseline: OptimizationRun | None
) -> Scenario | None:
    """Derive a typed ``Scenario`` from a free-text what-if request.

    Returns ``None`` when no model/text is given or the LLM produces no usable
    changes — the caller then surfaces a blocked message rather than applying
    a guessed change.
    """
    if model is None or not (request_text or "").strip():
        return None

    from ..tools.graph_scenario import load_flow_chain

    labels = ", ".join(load_flow_chain().echelons)
    system = _SYSTEM.format(
        labels=labels,
        no_baseline_rule="" if baseline is not None else _NO_BASELINE_RULE,
    )

    sections = []
    if baseline is not None:
        schema_txt = format_summary_for_prompt(summarize_data(baseline.input_data or []))
        obj = baseline.formulation.objective
        sections.append(f"## Baseline data schema\n{schema_txt}")
        sections.append(f"## Baseline objective\n{obj.sense} {obj.expression}")
    else:
        sections.append("## Baseline\n(none in this session)")
    sections.append(f"## What-if request\n{request_text}")

    messages = [
        SystemMessage(content=system),
        HumanMessage(content="\n\n".join(sections)),
    ]
    try:
        draft = model.with_structured_output(_ScenarioDraft).invoke(messages)
    except Exception as exc:  # noqa: BLE001 — any LLM/parse failure is non-fatal
        logger.warning("scenario_from_request: structured-output failed: %s", exc)
        return None

    if draft is None or not (
        getattr(draft, "perturbations", None) or getattr(draft, "graph_edits", None)
    ):
        logger.warning("scenario_from_request: no changes derived")
        return None

    perturbations = list(draft.perturbations) if baseline is not None else []
    return Scenario(
        scenario_id=uuid.uuid4().hex[:8],
        name=draft.name or "What-if scenario",
        baseline_id=(baseline.run_id or "") if baseline is not None else "",
        description=draft.description,
        perturbations=perturbations,
        graph_edits=list(draft.graph_edits),
    )
