"""Shared Pydantic schemas for GRASS.

Contains structured output models used across agents (e.g. plan generation).
Extracted from plan_agent.py to break import coupling.
"""

from typing import Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    agent: Literal["Cypher", "Analytics", "Optimization"] = Field(
        description="Which worker agent to invoke for this step."
    )
    task: str = Field(
        description="Concrete task description for the agent."
    )


class PlanOutput(BaseModel):
    """Structured output produced by the Plan Agent / Supervisor."""

    intent: Literal[
        "greeting",
        "factual_lookup",
        "analytical",
        "spatial",
        "optimization",
        "report",
        "conversational",
        "unclear",
    ] = Field(description="Classified intent of the user query.")

    message: str = Field(
        description=(
            "Natural-language response. For conversational: a helpful answer. "
            "For unclear: a specific clarification question. "
            "For other intents: a brief summary of the plan."
        )
    )

    summary: str = Field(
        default="",
        description="One-sentence description of the plan goal (empty for conversational/unclear).",
    )

    steps: list[PlanStep] = Field(
        default_factory=list,
        description="Ordered list of agent steps (empty for conversational/unclear).",
    )

    requires_geo: bool = Field(
        default=False,
        description="True when the query involves geographic/spatial data.",
    )

    requires_optimization: bool = Field(
        default=False,
        description="True when the query requires optimization.",
    )


# ── Optimization formulation (OptiMUS-inspired) ─────────────────────


class OptSet(BaseModel):
    """A named set in the optimization model (e.g., set of farms)."""
    definition: str = Field(description="What this set represents.")
    size_from: str = Field(description="Column or expression that determines cardinality.")


class OptParameter(BaseModel):
    """A known value in the model (data-driven)."""
    definition: str = Field(description="What this parameter represents.")
    source_type: Literal["column", "computed", "constant", "estimated"] = Field(
        description="How the value is obtained."
    )
    source_value: str = Field(
        description="Column name if 'column', formula if 'computed', value if 'constant'."
    )


class OptVariable(BaseModel):
    """A decision variable to be optimized."""
    type: Literal["continuous", "integer", "binary"] = Field(
        description="Variable type for the solver."
    )
    bounds: str = Field(default=">= 0", description="Variable bounds.")
    definition: str = Field(description="What this variable represents.")


class OptConstraint(BaseModel):
    """A constraint on the decision variables."""
    name: str = Field(description="Short constraint identifier.")
    expression: str = Field(
        description="Pseudo-mathematical expression, e.g. 'for each i: sum_j x[i,j] <= supply[i]'."
    )


class OptObjective(BaseModel):
    """The objective function."""
    sense: Literal["minimize", "maximize"] = Field(description="Optimization direction.")
    expression: str = Field(description="Objective expression.")


class OptimizationFormulation(BaseModel):
    """Complete structured optimization formulation (OptiMUS-inspired).

    Produced by Stage 1 of the Optimization Agent pipeline.
    Persisted in state as optimization_model for what-if reuse.
    """
    problem_type: Literal[
        "transportation", "facility_location", "inventory",
        "assignment", "routing", "blending", "custom"
    ] = Field(description="Category of optimization problem.")
    description: str = Field(description="One-sentence problem description.")
    sets: dict[str, OptSet] = Field(default_factory=dict, description="Named sets.")
    parameters: dict[str, OptParameter] = Field(default_factory=dict, description="Known parameters.")
    variables: dict[str, OptVariable] = Field(default_factory=dict, description="Decision variables.")
    objective: OptObjective = Field(description="Objective function.")
    constraints: list[OptConstraint] = Field(default_factory=list, description="Model constraints.")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions made.")
    data_reduction: str = Field(default="", description="Strategy for handling large data.")
