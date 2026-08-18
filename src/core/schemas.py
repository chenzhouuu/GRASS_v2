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


class ReportSection(BaseModel):
    """One narrative section of the PDF report."""

    heading: str = Field(description="Section heading, e.g. 'Analysis & Findings'.")
    body: str = Field(
        default="",
        description="Section prose. Plain-text paragraphs; no markdown or code.",
    )
    bullets: list[str] = Field(
        default_factory=list,
        description="Optional bullet points rendered after the body.",
    )


class ReportContent(BaseModel):
    """Narrative content of the PDF report.

    The Report Agent produces ONLY this content; page layout, tables of
    optimization routes/KPIs, and the appendix are rendered by fixed code
    (src/tools/report_renderer.py).
    """

    title: str = Field(description="Report title, concise and specific (<= 80 chars).")
    executive_summary: str = Field(
        description="One paragraph: key findings and top recommendation, with exact numbers."
    )
    sections: list[ReportSection] = Field(
        description="2-4 narrative sections (data overview, findings, interpretation)."
    )
    recommendations: list[str] = Field(
        description="3-5 specific, actionable next steps."
    )
    limitations: str = Field(
        default="",
        description="Short paragraph on data caveats and scope limits.",
    )


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


# ── What-if scenario engine — solved-instance snapshot (P0) ─────────


class KPI(BaseModel):
    """A single normalized key performance indicator extracted from a solution."""
    name: str = Field(description="KPI identifier, e.g. 'total_route_cost'.")
    value: float = Field(description="Scalar value.")
    unit: str = Field(default="", description="Display unit, e.g. '$', 'lbs'.")


class OptimizationRun(BaseModel):
    """A solved optimization instance snapshot — the unit of what-if comparison.

    The baseline run is persisted in state as ``optimization_baseline`` so a
    later scenario can perturb its data and re-run the cached ``code`` without
    re-formulating (OptiMUS-style model/data separation).
    """
    run_id: str = Field(description="Unique id for this solved instance.")
    scenario_id: str | None = Field(
        default=None, description="None for the baseline run; set for scenario runs."
    )
    formulation: OptimizationFormulation = Field(description="The structured model that was solved.")
    code: str = Field(default="", description="Generated PuLP code (cached for scenario re-solve).")
    status: str = Field(default="", description="Solver status, e.g. 'Optimal'.")
    objective: float | None = Field(default=None, description="Objective value if solved.")
    kpis: list[KPI] = Field(default_factory=list, description="Normalized KPIs.")
    duals: dict = Field(
        default_factory=dict, description="Constraint name → shadow price (LP only)."
    )
    binding_constraints: list[str] = Field(
        default_factory=list, description="Names of binding (zero-slack) constraints."
    )
    routes: list[dict] = Field(default_factory=list, description="Solution routes/flows.")
    input_data: list[dict] = Field(
        default_factory=list,
        description="Rows the model solved on (baseline only) — perturbed by scenarios.",
    )
    input_path: str = Field(
        default="",
        description=(
            "Project-root-relative path the cached code reads its input from "
            "(baked in at codegen). Scenario re-solves MUST write perturbed "
            "rows to this exact path; empty means the baseline predates path "
            "recording and cannot be safely re-solved."
        ),
    )


# ── What-if scenario engine — scenario definition (P1) ──────────────


class Perturbation(BaseModel):
    """One typed change against the baseline.

    All kinds except ``structural`` are applied deterministically to the
    baseline's data rows (no LLM). ``structural`` (add/relax a constraint or
    bound) is deferred to P3 and applied by editing the formulation.
    """
    kind: Literal[
        "scale_param",     # multiply a numeric column by ``factor`` (demand ×1.2)
        "set_param",       # set a numeric column to absolute ``value``
        "scale_capacity",  # scale a capacity column by ``factor`` (mechanically == scale_param)
        "remove_entity",   # drop rows matching ``selector`` (Processor X offline)
        "structural",      # constraint/bound change applied via the formulation (P3)
    ] = Field(description="Perturbation type.")
    target: str = Field(
        default="",
        description="Column/parameter this applies to (empty for remove_entity / structural).",
    )
    selector: dict = Field(
        default_factory=dict,
        description="Row filter, e.g. {'name': 'Processor X'}; empty = all rows.",
    )
    factor: float | None = Field(default=None, description="Multiplier for scale_* kinds.")
    value: float | None = Field(default=None, description="Absolute value for set_param.")
    instruction: str = Field(default="", description="NL instruction for kind=structural.")


class GraphEdit(BaseModel):
    """One structural edit on the graph view of a scenario (Layer 1).

    Graph edits never write to Neo4j: removed entities are excluded from
    read queries via parameterized predicates at query time, so structural
    impact tools (reachability, cascade trace, nearest alternatives) work
    without an optimization baseline.
    """
    op: Literal["remove_node"] = Field(
        default="remove_node", description="Edit operation (P1: node removal only)."
    )
    label: str = Field(description="Node label, e.g. 'Processor'.")
    name: str = Field(
        default="",
        description="Entity display name; resolved to an id at execution time. "
        "Ambiguous names (duplicates exist in this graph) raise with candidates.",
    )
    id: str = Field(
        default="",
        description="Entity id (e.g. processor_id). Takes precedence over name.",
    )


class Scenario(BaseModel):
    """A named what-if = a diff against a baseline + the comparison spec.

    Fully reproducible from its recipe (``baseline_id`` + ordered
    ``perturbations``), mirroring mpi-sppy's ``(name, kwargs)`` contract.
    ``graph_edits`` carry the Layer-1 structural view (graph reachability);
    ``perturbations`` carry the Layer-2 numeric view (LP re-solve). An
    entity-outage scenario typically has both.
    """
    scenario_id: str = Field(description="Unique id for this scenario.")
    name: str = Field(description="Short human label, e.g. 'Processor X offline'.")
    baseline_id: str = Field(default="", description="run_id of the baseline this perturbs.")
    description: str = Field(default="", description="NL description for display/provenance.")
    perturbations: list[Perturbation] = Field(default_factory=list)
    graph_edits: list[GraphEdit] = Field(default_factory=list)
    requested_kpis: list[str] = Field(
        default_factory=list, description="KPIs to compare in the report (P2)."
    )


# ── What-if scenario engine — before/after comparison (P2) ──────────


class KpiDelta(BaseModel):
    """One KPI's baseline→scenario change, with direction-aware coloring hint."""
    name: str
    baseline: float
    scenario: float
    delta: float
    pct: float | None = Field(default=None, description="Percent change; None if baseline is 0.")
    unit: str = ""
    good_direction: Literal["up", "down", "flat"] = Field(
        default="flat",
        description="Which direction is favorable (drives green/red in the UI).",
    )


class ScenarioComparison(BaseModel):
    """Baseline-vs-scenario comparison produced by the interpreter (deterministic
    deltas + binding-constraint shift + objective waterfall + narrative)."""
    baseline_run_id: str
    scenario_run_id: str
    scenario_name: str = ""
    scenario_description: str = ""
    objective_sense: str = "minimize"
    objective_baseline: float | None = None
    objective_scenario: float | None = None
    kpi_deltas: list[KpiDelta] = Field(default_factory=list)
    binding_added: list[str] = Field(
        default_factory=list, description="Constraints newly binding in the scenario."
    )
    binding_removed: list[str] = Field(
        default_factory=list, description="Constraints no longer binding in the scenario."
    )
    waterfall: dict | None = Field(
        default=None, description="Plotly waterfall spec: baseline → Δ → scenario."
    )
    narrative: str = Field(default="", description="Model- or rule-generated 'why' explanation.")
