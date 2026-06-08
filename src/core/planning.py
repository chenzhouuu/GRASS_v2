"""Co-planning data contracts.

Ported from Magentic-UI v0.1.6 (``src/magentic_ui/types.py`` and
``teams/orchestrator/_utils.py`` / ``_prompts.py``). The protocol is
reproduced faithfully; the only intentional divergence is that
``PlanStep.agent`` is constrained to the GRASS worker roster (Magentic
uses a free-form ``agent_name``), and ``SentinelPlanStep`` is omitted
(GRASS has no long-running monitoring tasks).

Contracts:
- ``PlanStep`` / ``Plan``        — the editable plan artifact
- ``HumanInputFormat``           — the human's resume payload {content, accepted, plan}
- ``is_accepted_str``            — acceptance-phrase detection (verbatim port)
- ``extract_json_from_string``   — lenient JSON extraction (verbatim port)
- ``validate_plan_json``         — plan-JSON schema validation (port, non-sentinel)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# GRASS worker roster — the only valid agents for a plan step.
GRASS_AGENTS = ("Cypher", "Analytics", "Optimization", "Report")
AgentName = Literal["Cypher", "Analytics", "Optimization", "Report"]

_AGENT_LOOKUP = {a.lower(): a for a in GRASS_AGENTS}


def _normalize_agent(value: str) -> Optional[str]:
    """Map a raw agent string to the canonical GRASS worker name.

    Returns ``None`` for unknown agents (the step is then dropped, with a
    warning) — we never silently coerce to an arbitrary worker.
    """
    if not value:
        return None
    return _AGENT_LOOKUP.get(value.strip().lower())


# ── Plan artifact (port of types.PlanStep / types.Plan) ──────────────


class PlanStep(BaseModel):
    """A single step in a plan. Mirrors Magentic-UI ``PlanStep``.

    ``agent`` corresponds to Magentic's ``agent_name``, constrained to the
    GRASS worker roster. ``enabled`` is carried from the frontend
    ``IPlanStep`` contract so the human can drop a step when editing.
    """

    title: str
    details: str
    agent: AgentName
    enabled: bool = True


class Plan(BaseModel):
    """An ordered, editable plan. Mirrors Magentic-UI ``Plan``."""

    task: Optional[str] = None
    summary: str = ""  # = Magentic ``plan_summary``
    steps: list[PlanStep] = Field(default_factory=list)
    # GRASS-specific UI signals (carried over from the legacy PlanOutput).
    requires_geo: bool = False
    requires_optimization: bool = False

    def __len__(self) -> int:
        return len(self.steps)

    def __getitem__(self, index: int) -> PlanStep:
        return self.steps[index]

    def to_plan_str(self) -> str:
        """Render the plan as text (port of ``Plan.__str__``)."""
        lines: list[str] = []
        if self.task:
            lines.append(f"Task: {self.task}")
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        for i, step in enumerate(self.steps):
            flag = "" if step.enabled else "  [disabled]"
            lines.append(f"{i + 1}. {step.agent}: {step.title}{flag}\n   {step.details}")
        return "\n".join(lines)

    @classmethod
    def from_obj(
        cls, data: "Plan | dict[str, Any] | list[Any] | str | None"
    ) -> Optional["Plan"]:
        """Build a ``Plan`` from a JSON string, dict, list of steps, or Plan.

        Port of ``Plan.from_list_of_dicts_or_str`` widened to also accept the
        full plan-JSON object (with ``task``/``plan_summary``/``steps``).
        Returns ``None`` when there is nothing usable.
        """
        if data is None:
            return None
        if isinstance(data, Plan):
            return data
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                return None

        task: Optional[str] = None
        summary = ""
        requires_geo = False
        requires_optimization = False

        if isinstance(data, dict):
            task = data.get("task")
            summary = data.get("plan_summary", data.get("summary", "")) or ""
            requires_geo = bool(data.get("requires_geo", False))
            requires_optimization = bool(data.get("requires_optimization", False))
            raw_steps = data.get("steps", [])
        elif isinstance(data, list):
            raw_steps = data
        else:
            return None

        steps: list[PlanStep] = []
        for raw in raw_steps:
            if not isinstance(raw, dict):
                continue
            agent = _normalize_agent(raw.get("agent") or raw.get("agent_name") or "")
            if agent is None:
                logger.warning(
                    "Plan.from_obj: dropping step with unknown agent %r",
                    raw.get("agent") or raw.get("agent_name"),
                )
                continue
            steps.append(
                PlanStep(
                    title=raw.get("title", "Untitled Step"),
                    details=raw.get("details", "No details provided."),
                    agent=agent,
                    enabled=bool(raw.get("enabled", True)),
                )
            )

        if not steps and task is None:
            return None
        return cls(
            task=task,
            summary=summary,
            steps=steps,
            requires_geo=requires_geo,
            requires_optimization=requires_optimization,
        )


# ── Human resume payload (port of types.HumanInputFormat) ────────────


class HumanInputFormat(BaseModel):
    """The human's response to a proposed plan.

    Mirrors Magentic-UI ``HumanInputFormat``: ``accepted`` flags approval,
    ``plan`` carries an edited plan (adopted whether accepted or not),
    ``content`` is free-text feedback (also checked via ``is_accepted_str``).
    """

    content: str = ""
    accepted: bool = False
    plan: Optional[Plan] = None

    @classmethod
    def from_obj(cls, data: "HumanInputFormat | dict[str, Any] | str | None") -> "HumanInputFormat":
        """Lenient parse (port of ``from_str`` + ``from_dict``)."""
        if isinstance(data, HumanInputFormat):
            return data
        if data is None:
            return cls()
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                parsed = {"content": data}
            data = parsed if isinstance(parsed, dict) else {"content": str(data)}
        if not isinstance(data, dict):
            data = {"content": str(data)}
        raw_plan = data.get("plan")
        return cls(
            content=str(data.get("content", "")),
            accepted=bool(data.get("accepted", False)),
            plan=Plan.from_obj(raw_plan) if raw_plan else None,
        )


# ── Acceptance + JSON helpers (verbatim ports of _utils.py) ──────────

_ACCEPTED_STRS = {
    "accept",
    "accepted",
    "acept",
    "run",
    "execute plan",
    "execute",
    "looks good",
    "do it",
    "accept plan",
    "accpt",
    "run plan",
    "sounds good",
    "i don't know. use your best judgment.",
    "i don't know, you figure it out, don't ask me again.",
}


def is_accepted_str(user_input: str) -> bool:
    """Whether free-text input means 'accept the plan' (port of _utils)."""
    return user_input.lower().strip() in _ACCEPTED_STRS


def extract_json_from_string(s: str) -> Optional[Any]:
    """Return the first JSON object embedded in ``s`` (port of _utils)."""
    match = re.search(r"\{.*\}", s, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


# ── Progress-ledger contracts (port of _prompts.validate_ledger_json) ─

# Port of _prompts.INSTRUCTION_AGENT_FORMAT — becomes the worker_task.
INSTRUCTION_AGENT_FORMAT = (
    "Step {step_index}: {step_title}\n\n"
    "{step_details}\n\n"
    "Instruction for {agent_name}: {instruction}"
)


def validate_ledger_json(json_response: Any, agent_names: list[str]) -> bool:
    """Validate a progress-ledger response (port of _prompts.validate_ledger_json)."""
    if not isinstance(json_response, dict):
        return False
    required = [
        "is_current_step_complete",
        "need_to_replan",
        "instruction_or_question",
        "progress_summary",
    ]
    if any(key not in json_response for key in required):
        return False
    for key in ("is_current_step_complete", "need_to_replan"):
        block = json_response[key]
        if not isinstance(block, dict) or "reason" not in block or "answer" not in block:
            return False
    ioq = json_response["instruction_or_question"]
    if not isinstance(ioq, dict) or "answer" not in ioq or "agent_name" not in ioq:
        return False
    if ioq["agent_name"] not in agent_names:
        return False
    if not isinstance(json_response["progress_summary"], str):
        return False
    return True


def validate_plan_json(json_response: Any) -> bool:
    """Validate the plan-JSON schema (port of _prompts.validate_plan_json, non-sentinel)."""
    if not isinstance(json_response, dict):
        return False
    required = ["task", "steps", "needs_plan", "response", "plan_summary"]
    if any(key not in json_response for key in required):
        return False
    steps = json_response["steps"]
    if not isinstance(steps, list):
        return False
    for item in steps:
        if not isinstance(item, dict):
            return False
        if "title" not in item or "details" not in item:
            return False
        if "agent" not in item and "agent_name" not in item:
            return False
    return True
