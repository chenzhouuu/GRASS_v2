"""Translate a free-text what-if request into a typed ``Scenario``.

Single source of truth for deriving structured ``Perturbation``s from natural
language. Used by ``ScenarioRunner`` when invoked in plan mode (no pre-built
``pending_scenario``). Direct mode keeps building ``pending_scenario`` via the
Supervisor's ``define_scenario`` tool and skips this path.
"""

import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..core.schemas import OptimizationRun, Perturbation, Scenario
from ..utils.data_summarizer import format_summary_for_prompt, summarize_data

logger = logging.getLogger(__name__)

_SYSTEM = """You translate a supply-chain what-if request into a structured set of
perturbations against an existing optimization baseline.

Perturbation kinds:
- scale_param: multiply numeric column `target` by `factor` (transport cost +25% -> factor 1.25)
- set_param: set numeric column `target` to absolute `value`
- scale_capacity: scale a capacity column `target` by `factor` (plant at 2/3 -> factor 0.6667)
- remove_entity: drop rows matching `selector` (e.g. {"processor_id": "P0042"})
- structural: a constraint/bound change expressed in `instruction` (no numeric column)

Rules:
- Only reference columns that appear in the baseline data schema below.
- Prefer a unique id column in `selector` (e.g. processor_id) over a display name.
- Emit at least one perturbation. If you cannot map the request to any column, emit an empty list."""


class _ScenarioDraft(BaseModel):
    """LLM-facing draft: name + description + typed perturbations (no ids)."""
    name: str = Field(default="What-if scenario", description="Short label.")
    description: str = Field(default="", description="One-line description.")
    perturbations: list[Perturbation] = Field(default_factory=list)


def scenario_from_request(
    model: Any, request_text: str, baseline: OptimizationRun
) -> Scenario | None:
    """Derive a typed ``Scenario`` from a free-text what-if request.

    Returns ``None`` when no model/text is given or the LLM produces no usable
    perturbations — the caller then surfaces a blocked message rather than
    applying a guessed change.
    """
    if model is None or not (request_text or "").strip():
        return None

    schema_txt = format_summary_for_prompt(summarize_data(baseline.input_data or []))
    obj = baseline.formulation.objective
    user_content = (
        f"## Baseline data schema\n{schema_txt}\n\n"
        f"## Baseline objective\n{obj.sense} {obj.expression}\n\n"
        f"## What-if request\n{request_text}"
    )
    messages = [SystemMessage(content=_SYSTEM), HumanMessage(content=user_content)]
    try:
        draft = model.with_structured_output(_ScenarioDraft).invoke(messages)
    except Exception as exc:  # noqa: BLE001 — any LLM/parse failure is non-fatal
        logger.warning("scenario_from_request: structured-output failed: %s", exc)
        return None

    if draft is None or not getattr(draft, "perturbations", None):
        logger.warning("scenario_from_request: no perturbations derived")
        return None

    return Scenario(
        scenario_id=uuid.uuid4().hex[:8],
        name=draft.name or "What-if scenario",
        baseline_id=baseline.run_id or "",
        description=draft.description,
        perturbations=list(draft.perturbations),
    )
