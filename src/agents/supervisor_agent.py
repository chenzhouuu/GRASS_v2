"""Supervisor Agent — single orchestrator replacing Plan + Process +
Replanner + Response agents.

Uses tool-calling to route tasks to workers:
- Local tools (generate_plan, get_neo4j_schema) execute within the
  Supervisor and loop back for the next decision.
- Handoff tools (dispatch_cypher, dispatch_analytics, etc.) break the loop
  and route to a worker node via the ``next_worker`` state field.
- No tool calls = Supervisor produces the final user-facing markdown
  response directly.
"""

import logging
import uuid
from typing import Any, Literal

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from ..utils.prompt_assembler import PromptAssembler
from ..utils.schema_loader import get_schema as load_schema_text
from ..core.schemas import PlanOutput
from ..tools.geo_extractor import extract_geo_data as _extract_geo_data_fn

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10
MAX_HISTORY_MESSAGES = 40


# ── Deterministic data-shape analysis ────────────────────────────────


def _infer_presentation_hint(cypher_results: list[dict], state: dict) -> str | None:
    """Analyze data shape to determine if visualization is warranted.

    Returns a context hint for the Supervisor, or None.
    This is a deterministic guardrail — it analyzes the DATA SHAPE,
    not the query keywords.  Prevents the Supervisor from answering
    multi-row comparative data as plain text when a chart would be better.
    """
    # Skip if already visualized or analyzed
    if state.get("chart_specs") or state.get("analysis_results"):
        return None

    if not cypher_results or len(cypher_results) < 3:
        return None  # Single/few values → text is fine

    first = cypher_results[0]
    col_types = {}
    for k, v in first.items():
        if isinstance(v, str):
            col_types[k] = "categorical"
        elif isinstance(v, (int, float)):
            col_types[k] = "numeric"

    has_categorical = "categorical" in col_types.values()
    has_numeric = "numeric" in col_types.values()

    if has_categorical and has_numeric:
        cat_cols = [k for k, t in col_types.items() if t == "categorical"]
        num_cols = [k for k, t in col_types.items() if t == "numeric"]
        return (
            f"[Data shape: {len(cypher_results)} rows with "
            f"categorical columns ({', '.join(cat_cols)}) and "
            f"numeric columns ({', '.join(num_cols)}). "
            f"IMPORTANT: Dispatch to Analytics Agent for chart visualization. "
            f"Multi-row data with categories and numbers should be visualized, "
            f"not listed as text.]"
        )

    return None


# ── tool schemas for LLM binding ──────────────────────────────────

class GeneratePlanInput(BaseModel):
    """Input schema for the generate_plan tool."""
    query: str = Field(description="The user query to create a plan for.")


class DispatchInput(BaseModel):
    """Input schema for worker dispatch tools."""
    task: str = Field(description="Concrete task description for the worker agent.")


class EmptyInput(BaseModel):
    """Input schema for tools that take no arguments."""
    pass


class PerturbationInput(BaseModel):
    """One typed what-if change against the baseline optimization."""
    kind: Literal[
        "scale_param", "set_param", "scale_capacity", "remove_entity", "structural"
    ] = Field(description="Perturbation type.")
    target: str = Field(default="", description="Numeric column/parameter to change (empty for remove_entity/structural).")
    selector: dict = Field(default_factory=dict, description="Row filter, e.g. {'name': 'Processor X'}; empty = all rows.")
    factor: float | None = Field(default=None, description="Multiplier for scale_param/scale_capacity (e.g. 1.2 = +20%).")
    value: float | None = Field(default=None, description="Absolute value for set_param.")
    instruction: str = Field(default="", description="Natural-language change for kind=structural (P3).")


class DefineScenarioInput(BaseModel):
    """Input schema for the define_scenario tool."""
    name: str = Field(description="Short label, e.g. 'Demand +20%' or 'Processor X offline'.")
    description: str = Field(default="", description="One-line natural-language description of the what-if.")
    perturbations: list[PerturbationInput] = Field(
        default_factory=list, description="Ordered list of typed changes against the baseline."
    )


class SweepFactorInput(BaseModel):
    """One factor in a sensitivity sweep (varied low↔high while others held)."""
    name: str = Field(description="Display label, e.g. 'Retailer demand'.")
    target: str = Field(description="Numeric column/parameter to vary, e.g. 'demand'.")
    low: float = Field(default=0.8, description="Low multiplier (e.g. 0.8 = -20%).")
    high: float = Field(default=1.2, description="High multiplier (e.g. 1.2 = +20%).")
    selector: dict = Field(default_factory=dict, description="Optional row filter; empty = all rows.")


class DefineSweepInput(BaseModel):
    """Input schema for the define_sweep tool (tornado sensitivity)."""
    factors: list[SweepFactorInput] = Field(
        default_factory=list, description="Factors to vary one-at-a-time around the baseline."
    )


# ── agent class ───────────────────────────────────────────────────

class SupervisorAgent:
    """Supervisor Agent with tool-calling orchestration loop.

    Parameters
    ----------
    model : BaseChatModel
        A LangChain chat model that supports tool calling.
    plan_model : BaseChatModel | None
        Model for plan generation (structured output). Defaults to
        the same model if not provided.
    prompt_assembler : PromptAssembler | None
        Custom prompt assembler. Created automatically if not provided.
    """

    agent_name = "supervisor"

    def __init__(
        self,
        model,
        plan_model=None,
        prompt_assembler: PromptAssembler | None = None,
    ):
        self.prompt_assembler = prompt_assembler or PromptAssembler()
        self._plan_model = plan_model or model

        # Define tool schemas for the LLM
        self._tool_schemas = self._build_tool_schemas()
        self.model = model.bind_tools(self._tool_schemas)

        # Local tool implementations (execute in Supervisor, loop back)
        self._local_tools: dict[str, Any] = {
            "generate_plan": self._generate_plan,
            "get_neo4j_schema": self._get_schema,
            "extract_geo_data": self._extract_geo_data,
            "define_scenario": self._define_scenario,
            "define_sweep": self._define_sweep,
        }

        # Handoff map: tool name -> worker node name
        self._handoff_map: dict[str, str] = {
            "dispatch_cypher": "Cypher",
            "dispatch_analytics": "Analytics",
            "dispatch_optimization": "Optimization",
            "finish_with_report": "Report",
            "dispatch_scenario": "ScenarioRunner",
            "dispatch_sweep": "ScenarioRunner",
        }

    def _build_tool_schemas(self) -> list:
        """Build LangChain-compatible tool definitions."""
        from langchain_core.tools import StructuredTool

        tools = [
            StructuredTool.from_function(
                func=lambda query="": "",
                name="generate_plan",
                description=(
                    "Create a structured execution plan for complex multi-step "
                    "queries requiring multiple agents. Skip for simple lookups "
                    "or follow-up questions."
                ),
                args_schema=GeneratePlanInput,
            ),
            StructuredTool.from_function(
                func=lambda: "",
                name="get_neo4j_schema",
                description=(
                    "Retrieve the current Neo4j database schema (node labels, "
                    "relationships, properties, graph patterns). Use when you "
                    "need to verify available data or debug empty query results."
                ),
                args_schema=EmptyInput,
            ),
            StructuredTool.from_function(
                func=lambda task: f"Dispatching to Cypher Agent: {task}",
                name="dispatch_cypher",
                description=(
                    "Send a task to the Cypher Agent for Neo4j graph queries. "
                    "Use for data retrieval, aggregation, path queries, spatial "
                    "lookups."
                ),
                args_schema=DispatchInput,
            ),
            StructuredTool.from_function(
                func=lambda task: f"Dispatching to Analytics Agent: {task}",
                name="dispatch_analytics",
                description=(
                    "Send a task to the Analytics Agent for Python data analysis "
                    "(pandas, scipy, scikit-learn) AND interactive Plotly chart "
                    "generation. Use for statistical analysis, trend detection, "
                    "distribution plots, comparison charts, heatmaps, Sankey "
                    "diagrams, and any visualization request."
                ),
                args_schema=DispatchInput,
            ),
            StructuredTool.from_function(
                func=lambda: "",
                name="extract_geo_data",
                description=(
                    "Extract geographic data from Cypher results as GeoJSON "
                    "for the frontend map. Call this AFTER Cypher returns "
                    "results containing lat/lon coordinates. Returns a GeoJSON "
                    "FeatureCollection with Point markers or LineString routes."
                ),
                args_schema=EmptyInput,
            ),
            StructuredTool.from_function(
                func=lambda task: f"Dispatching to Optimization Agent: {task}",
                name="dispatch_optimization",
                description=(
                    "Send a task to the Optimization Agent for LP/MILP "
                    "optimization (PuLP). Use for transportation cost "
                    "minimization, facility location, inventory optimization."
                ),
                args_schema=DispatchInput,
            ),
            StructuredTool.from_function(
                func=lambda name="", description="", perturbations=None: "",
                name="define_scenario",
                description=(
                    "Define a what-if scenario against the EXISTING baseline "
                    "optimization (requires a prior optimization in this session). "
                    "Use for questions like 'what if demand rises 20%', 'what if "
                    "Processor X goes offline', 'what if DC capacity is halved'. "
                    "Express each change as a typed perturbation: scale_param "
                    "(factor, e.g. demand x1.2), set_param (value), scale_capacity "
                    "(factor), or remove_entity (selector). After defining, call "
                    "dispatch_scenario to run it. Do NOT call dispatch_optimization "
                    "for a what-if — reuse the baseline."
                ),
                args_schema=DefineScenarioInput,
            ),
            StructuredTool.from_function(
                func=lambda: "Dispatching to Scenario Runner.",
                name="dispatch_scenario",
                description=(
                    "Run the scenario defined by define_scenario: re-solve the "
                    "baseline on perturbed data and produce a before/after "
                    "comparison (KPI deltas, binding-constraint shift, waterfall). "
                    "Call only after define_scenario."
                ),
                args_schema=EmptyInput,
            ),
            StructuredTool.from_function(
                func=lambda factors=None: "",
                name="define_sweep",
                description=(
                    "Define a one-factor sensitivity sweep against the baseline "
                    "optimization. Use for 'which factor matters most', 'sensitivity "
                    "analysis', or 'tornado'. Each factor is varied low↔high (e.g. "
                    "±20%) while others stay fixed; the result is a tornado chart "
                    "ranking each factor's objective impact. Then call dispatch_sweep."
                ),
                args_schema=DefineSweepInput,
            ),
            StructuredTool.from_function(
                func=lambda: "Dispatching sensitivity sweep to Scenario Runner.",
                name="dispatch_sweep",
                description="Run the sweep defined by define_sweep and produce a tornado chart.",
                args_schema=EmptyInput,
            ),
            StructuredTool.from_function(
                func=lambda: "Dispatching to Report Agent for PDF generation.",
                name="finish_with_report",
                description=(
                    "Route to the Report Agent for PDF report generation "
                    "(fpdf2). Use only after all data gathering and analysis "
                    "is complete."
                ),
                args_schema=EmptyInput,
            ),
        ]
        return tools

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the Supervisor's tool-calling loop.

        Returns a state-update dict. The ``next_worker`` field determines
        routing:
        - ``None`` → END (Supervisor produced final response)
        - ``"Cypher"`` / ``"Analytics"`` / etc. → route to that worker
        """
        messages = self._build_messages(state)
        # Per-invocation context — replaces mutable instance attributes so
        # concurrent requests sharing this agent instance cannot race.
        ctx: dict[str, Any] = {
            "state": state,
            "pending_plan": None,
            "pending_geo_data": None,
            "pending_scenario": None,
            "pending_sweep": None,
        }
        emitted_messages: list = []

        for iteration in range(MAX_ITERATIONS):
            response = self.model.invoke(messages)

            # No tool calls → Supervisor IS the responder
            if not response.tool_calls:
                emitted_messages.append(response)
                logger.info(
                    "Supervisor: producing final response (iteration %d)",
                    iteration,
                )
                result = {
                    "next_worker": None,
                    "response_markdown": response.content,
                    "messages": emitted_messages,
                    "sender": self.agent_name,
                }
                if ctx["pending_geo_data"]:
                    result["geo_data"] = ctx["pending_geo_data"]
                return result

            # Process the full assistant/tool exchange before continuing or handing off.
            new_messages = [response]
            handoff_worker: str | None = None
            handoff_task = ""

            for tool_call in response.tool_calls:
                name = tool_call.get("name", "")
                raw_args = tool_call.get("args", {})
                if raw_args is None:
                    args = {}
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    logger.warning(
                        "Supervisor: invalid args for tool '%s': expected dict, got %s",
                        name,
                        type(raw_args).__name__,
                    )
                    args = {}
                tool_call_id = tool_call.get(
                    "id",
                    f"missing-tool-call-id-{iteration}-{len(new_messages)}",
                )

                if name in self._local_tools:
                    # Execute locally, append result, continue loop
                    logger.info("Supervisor: calling local tool '%s'", name)
                    tool_result = self._local_tools[name](ctx, **args)

                elif name in self._handoff_map:
                    worker = self._handoff_map[name]
                    task = args.get("task", "")
                    tool_result = f"Dispatching to {worker}..."
                    if handoff_worker is None:
                        handoff_worker = worker
                        handoff_task = task
                        logger.info(
                            "Supervisor: dispatching to %s (task=%s)",
                            worker,
                            task[:80],
                        )
                    else:
                        logger.warning(
                            "Supervisor: multiple handoff tools requested in one response; "
                            "keeping first (%s), ignoring %s",
                            handoff_worker,
                            worker,
                        )
                        tool_result = (
                            f"Ignored additional handoff to {worker}; "
                            f"already dispatching to {handoff_worker}."
                        )

                else:
                    # Unknown tool — add error message and continue
                    logger.warning("Supervisor: unknown tool '%s'", name)
                    tool_result = f"Unknown tool: {name}"

                new_messages.append(
                    ToolMessage(
                        content=str(tool_result),
                        tool_call_id=tool_call_id,
                    )
                )

            if handoff_worker is not None:
                state_update: dict[str, Any] = {
                    "next_worker": handoff_worker,
                    "worker_task": handoff_task,
                    "messages": emitted_messages + new_messages,
                    "sender": self.agent_name,
                }

                # If we extracted geo data, include it
                if ctx["pending_geo_data"]:
                    state_update["geo_data"] = ctx["pending_geo_data"]

                # If we defined a what-if scenario, carry it to the ScenarioRunner
                if ctx["pending_scenario"]:
                    state_update["pending_scenario"] = ctx["pending_scenario"]

                # If we defined a sensitivity sweep, carry it to the ScenarioRunner
                if ctx["pending_sweep"]:
                    state_update["pending_sweep"] = ctx["pending_sweep"]

                # If we generated a plan, include it in state
                if ctx["pending_plan"]:
                    pending_plan = ctx["pending_plan"]
                    state_update["supervisor_plan"] = pending_plan
                    state_update["requires_geo"] = pending_plan.get(
                        "requires_geo", False
                    )
                    state_update["requires_optimization"] = pending_plan.get(
                        "requires_optimization", False
                    )

                return state_update

            messages.extend(new_messages)
            emitted_messages.extend(new_messages)

        # Safety: max iterations reached
        logger.warning("Supervisor: max iterations (%d) reached", MAX_ITERATIONS)
        return {
            "next_worker": None,
            "response_markdown": (
                "I was unable to fully complete the analysis within the "
                "allowed iterations. Here is what I found so far."
            ),
            "messages": emitted_messages + [
                AIMessage(
                    content="Max iterations reached.",
                    name=self.agent_name,
                )
            ],
            "sender": self.agent_name,
        }

    @staticmethod
    def _sanitize_message_content(content: str) -> str:
        """Remove large data artifacts from message content.

        Uses the shared Plotly marker stripper from plotly_markers.py.
        """
        from ..utils.plotly_markers import sanitize_for_supervisor
        return sanitize_for_supervisor(content)

    def _executed_worker_sequence(self, messages: list) -> list[str]:
        """Recover the ordered list of workers the Supervisor has dispatched.

        Reads handoff tool-call NAMES from the assistant messages in history
        (e.g. ``dispatch_cypher`` -> ``"Cypher"``). Tool-call names are a
        reliable agent identity, unlike ``past_steps`` entries, which store
        the worker's free-text task and carry no agent label.
        """
        seq: list[str] = []
        for msg in messages:
            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name in self._handoff_map:
                    seq.append(self._handoff_map[name])
        return seq

    def _build_messages(self, state: dict) -> list:
        """Build the message list for the Supervisor LLM call."""
        system_prompt = self.prompt_assembler.assemble()
        system = SystemMessage(content=system_prompt)
        history = list(state.get("messages", []))

        # Sanitize worker messages to prevent data artifacts in context
        sanitized_history = []
        for msg in history:
            if hasattr(msg, "content") and isinstance(msg.content, str):
                clean = self._sanitize_message_content(msg.content)
                if clean != msg.content:
                    msg = msg.copy(update={"content": clean})
            sanitized_history.append(msg)
        history = sanitized_history

        # Trim to prevent context overflow
        if len(history) > MAX_HISTORY_MESSAGES:
            history = [history[0]] + history[-MAX_HISTORY_MESSAGES:]

        # Inject worker results summary if returning from a worker
        context_parts = []
        if state.get("cypher_results"):
            results = state["cypher_results"]
            preview = str(results[:5]) if len(results) > 5 else str(results)
            context_parts.append(
                f"[Cypher results: {len(results)} records] {preview}"
            )
            # Data shape analysis: nudge toward Analytics for multi-row
            # categorical+numeric data (deterministic, not keyword-based)
            viz_hint = _infer_presentation_hint(results, state)
            if viz_hint:
                context_parts.append(viz_hint)
        if state.get("cypher_error"):
            context_parts.append(f"[Cypher error: {state['cypher_error']}]")
        if state.get("analysis_results"):
            context_parts.append(
                f"[Analysis results: {str(state['analysis_results'])[:500]}]"
            )
        if state.get("analysis_error"):
            context_parts.append(f"[Analysis error: {state['analysis_error']}]")
        if state.get("chart_specs"):
            context_parts.append(
                f"[Chart specs: {len(state['chart_specs'])} Plotly chart(s) generated]"
            )
        if state.get("geo_data"):
            feature_count = len(state["geo_data"].get("features", []))
            context_parts.append(
                f"[Geo data: {feature_count} features extracted for map]"
            )
        if state.get("optimization_model"):
            opt_model = state["optimization_model"]
            if isinstance(opt_model, dict):
                desc = opt_model.get("description", "")
                ptype = opt_model.get("problem_type", "custom")
                context_parts.append(f"[Optimization formulation: {ptype} — {desc}]")
            elif isinstance(opt_model, str) and opt_model:
                context_parts.append(f"[Optimization model: {opt_model[:200]}]")
        if state.get("optimization_solution"):
            context_parts.append(
                f"[Optimization solution: {state['optimization_solution']}]"
            )
        if state.get("optimization_error"):
            context_parts.append(
                f"[Optimization error: {state['optimization_error']}]"
            )
        if state.get("past_steps"):
            steps_summary = "; ".join(
                f"{t}: {r[:100]}" for t, r in state["past_steps"][-5:]
            )
            context_parts.append(f"[Past steps: {steps_summary}]")

        # Surface plan progress checklist.
        # A plan step is "done" only when a matching worker dispatch appears,
        # in order, in the Supervisor's own message history. We recover the
        # executed-worker sequence from dispatch tool-call NAMES (reliable
        # agent identity), then align the plan's agent sequence against it as
        # a SUBSEQUENCE. This is robust to off-plan corrective dispatches
        # (e.g. an extra Cypher to backfill coordinates) and retries, which
        # the old `len(past_steps)` positional heuristic mis-counted —
        # skipping real steps or marking the plan complete prematurely.
        # Prefer the co-planning Plan (mode="plan"); fall back to the legacy
        # supervisor_plan. Both expose steps keyed by `agent`; the co-planning
        # step carries title/details instead of `task`.
        plan = state.get("plan") or state.get("supervisor_plan")
        if plan and plan.get("steps"):
            plan_steps = plan["steps"]
            executed = self._executed_worker_sequence(state.get("messages", []))

            done_flags: list[bool] = []
            cursor = 0
            for step in plan_steps:
                step_agent = (step.get("agent") or "").strip().lower()
                matched = False
                while cursor < len(executed):
                    if executed[cursor].lower() == step_agent:
                        matched = True
                        cursor += 1
                        break
                    cursor += 1  # off-plan dispatch — skip it
                done_flags.append(matched)

            completed = sum(done_flags)
            total = len(plan_steps)

            plan_lines = ["## Plan Progress (EXECUTE STEPS IN ORDER)"]
            for i, (step, done) in enumerate(zip(plan_steps, done_flags)):
                step_agent = step.get("agent", "")
                step_task = (
                    step.get("task")
                    or step.get("details")
                    or step.get("title")
                    or step.get("description", "")
                )
                mark = "[x]" if done else "[ ]"
                suffix = " — DONE" if done else ""
                plan_lines.append(
                    f"  {mark} Step {i+1}: [{step_agent}] {step_task[:80]}{suffix}"
                )

            # Next action = first incomplete step (not simply the n-th).
            next_idx = next(
                (i for i, done in enumerate(done_flags) if not done), None
            )
            if next_idx is not None:
                next_step = plan_steps[next_idx]
                next_agent = next_step.get("agent", "?")
                next_task = (
                    next_step.get("task")
                    or next_step.get("details")
                    or next_step.get("title")
                    or next_step.get("description", "")
                )
                plan_lines.append(
                    f"\n  >>> NEXT ACTION: dispatch_{next_agent.lower()}"
                    f"(\"{next_task[:120]}\")"
                )
                remaining = total - completed
                if remaining > 1:
                    plan_lines.append(
                        f"  >>> {remaining} step(s) remaining. "
                        f"Do NOT skip to later steps or produce a final response."
                    )

            plan_text = "\n".join(plan_lines)
            logger.info("Plan progress (%d/%d done):\n%s", completed, total, plan_text)
            context_parts.append(plan_text)

        # Surface worker feedback prominently
        worker_feedback = state.get("worker_feedback", [])
        if worker_feedback:
            fb_lines = ["## Worker Feedback (REVIEW BEFORE RESPONDING)"]
            for fb in worker_feedback:
                fb_type = fb.get("type", "info")
                agent = fb.get("agent", "Unknown")
                msg = fb.get("message", "")
                if fb_type == "implausible_result":
                    fb_lines.append(f"- ALERT [{agent}]: {msg}")
                elif fb_type == "data_gap":
                    fb_lines.append(f"- WARNING [{agent}]: {msg}")
                    if "suggested_action" in fb:
                        fb_lines.append(f"  Suggested: {fb['suggested_action']}")
                elif fb_type == "trivial_solution":
                    fb_lines.append(f"- WARNING [{agent}]: {msg}")
                else:
                    fb_lines.append(f"- [{agent}]: {msg}")
            context_parts.append("\n".join(fb_lines))

        if context_parts:
            context_msg = SystemMessage(
                content="## Current State\n" + "\n".join(context_parts)
            )
            return [system, context_msg] + history
        return [system] + history

    # ── local tool implementations ────────────────────────────────

    def _generate_plan(self, ctx: dict, query: str) -> str:
        """Create a structured execution plan for complex multi-step queries."""
        try:
            plan_model = self._plan_model.with_structured_output(PlanOutput)
            plan_prompt = self._build_plan_prompt(query)
            result: PlanOutput = plan_model.invoke(plan_prompt)

            # Store for state update on next handoff
            ctx["pending_plan"] = {
                "intent": result.intent,
                "summary": result.summary,
                "steps": [s.model_dump() for s in result.steps],
                "requires_geo": result.requires_geo,
                "requires_optimization": result.requires_optimization,
            }

            # Return readable plan to Supervisor LLM
            steps = "\n".join(
                f"  {i + 1}. [{s.agent}] {s.task}"
                for i, s in enumerate(result.steps)
            )
            return (
                f"Plan generated:\n"
                f"Intent: {result.intent}\n"
                f"Summary: {result.summary}\n"
                f"Steps:\n{steps}\n"
                f"Requires GIS: {result.requires_geo}\n"
                f"Requires optimization: {result.requires_optimization}"
            )
        except Exception as exc:
            logger.error("generate_plan failed: %s", exc)
            return f"Plan generation failed: {exc}"

    def _build_plan_prompt(self, query: str) -> list:
        """Build the message list for the planning sub-call."""
        from langchain_core.messages import HumanMessage

        schema_text = load_schema_text(source="auto")
        plan_system = (
            "You are a planning assistant for a supply chain analytics system. "
            "Generate a structured execution plan.\n\n"
            "## Available Agents\n"
            "- Cypher: Query data from Neo4j\n"
            "- Analytics: Python analysis + Plotly chart generation "
            "(charts render in the CHAT panel as inline visualizations)\n"
            "- Optimization: LP/MILP optimization via PuLP\n\n"
            "## Artifact Routing (IMPORTANT)\n"
            "The frontend has separate rendering panels. Each artifact type "
            "renders in a specific location:\n\n"
            "| Artifact | Producer | Renders In |\n"
            "|----------|----------|-----------|\n"
            "| geo_data (GeoJSON) | Supervisor extract_geo_data OR Optimization Agent | "
            "Map panel (Leaflet) |\n"
            "| chart_specs (Plotly) | Analytics Agent | Chat panel (inline charts) |\n"
            "| response (markdown) | Supervisor | Chat panel (message) |\n\n"
            "## Key Routing Rules\n"
            "- The Optimization Agent AUTOMATICALLY generates route map data "
            "(geo_data) from its solution. Do NOT add an Analytics step just for "
            "map visualization after Optimization — the map renders automatically.\n"
            "- For map display of Cypher results (points, routes), the Supervisor "
            "calls extract_geo_data locally — no separate agent step needed.\n"
            "- Only dispatch Analytics when the user needs statistical analysis, "
            "Plotly charts (bar, scatter, heatmap, distribution), or data "
            "transformations beyond what Cypher aggregation provides.\n"
            "- 'Show on a map' = geo_data (automatic). 'Show a chart/plot' = Analytics.\n\n"
            "## Neo4j Schema\n\n"
            f"{schema_text}\n\n"
            "## Data Query Patterns for Optimization\n"
            "For optimization, use SEPARATE Cypher steps for supply and demand:\n\n"
            "**Step pattern**: One Cypher step per entity type.\n"
            "- Step A [Cypher]: Query SUPPLY entities (farms, cooperatives, or processors) "
            "with name, lat, lon, and volume/capacity. Use DISTINCT to avoid duplicates.\n"
            "- Step B [Cypher]: Query DEMAND entities (processors, DCs, or retailers) "
            "with name, lat, lon, and demand/capacity. Use DISTINCT.\n"
            "- Step C [Optimization]: Solve the LP/MILP using data from Steps A and B.\n\n"
            "Do NOT combine supply and demand in a single cross-product query — it creates "
            "N×M rows that overwhelm the optimizer. Keep each query to one entity type.\n\n"
            "**For large datasets (>200 entities)**: Aggregate farms by cooperative "
            "(12 cooperatives instead of 4940 farms) to keep the LP manageable.\n\n"
            "**Coordinates**: Always use n.lat, n.lon (NOT n.location POINT type).\n\n"
            "**Distances**: Do NOT compute distances in Cypher. The Optimization Agent "
            "computes haversine distances from lat/lon coordinates.\n\n"
            "## Rules\n"
            "- When query involves geographic/spatial aspects, set requires_geo=true "
            "and ensure Cypher retrieves lat, lon for ALL entities that need mapping.\n"
            "- When query involves optimization, set requires_optimization=true.\n"
            "- For greetings/conversational/unclear: set intent accordingly with a "
            "message and NO steps.\n"
            "- report intent MUST include data-gathering steps.\n"
            "- Keep plans concise (2-3 steps). Avoid unnecessary agent dispatches."
        )

        return [
            SystemMessage(content=plan_system),
            HumanMessage(content=query),
        ]

    def _get_schema(self, ctx: dict) -> str:
        """Retrieve the current Neo4j database schema."""
        try:
            return load_schema_text(source="auto")
        except Exception as exc:
            logger.error("get_neo4j_schema failed: %s", exc)
            return f"Schema fetch failed: {exc}"

    def _extract_geo_data(self, ctx: dict) -> str:
        """Extract GeoJSON from the most recent Cypher results."""
        try:
            cypher_results = ctx["state"].get("cypher_results") or []
            if not cypher_results:
                return "No Cypher results available to extract geo data from."

            geo_data = _extract_geo_data_fn(cypher_results)
            feature_count = len(geo_data.get("features", []))

            if feature_count == 0:
                return "No geographic columns (lat/lon) found in the Cypher results."

            ctx["pending_geo_data"] = geo_data
            return f"Extracted {feature_count} geographic features as GeoJSON."
        except Exception as exc:
            logger.error("extract_geo_data failed: %s", exc)
            return f"Geo data extraction failed: {exc}"

    def _define_scenario(
        self, ctx: dict, name: str = "", description: str = "", perturbations=None
    ) -> str:
        """Define a what-if scenario against the session's baseline optimization."""
        from ..core.schemas import Perturbation, Scenario

        baseline = ctx["state"].get("optimization_baseline")
        if not baseline:
            return (
                "No baseline optimization exists yet in this session. Run an "
                "optimization first (dispatch_optimization), then define the what-if."
            )

        perts: list[Perturbation] = []
        for p in (perturbations or []):
            try:
                perts.append(Perturbation(**p) if isinstance(p, dict) else Perturbation(**dict(p)))
            except Exception as exc:
                return f"Invalid perturbation {p!r}: {exc}"
        if not perts:
            return (
                "A what-if scenario needs at least one perturbation "
                "(e.g. scale_param target='demand' factor=1.2)."
            )

        scenario = Scenario(
            scenario_id=uuid.uuid4().hex[:8],
            name=name or "What-if scenario",
            baseline_id=baseline.get("run_id", ""),
            description=description,
            perturbations=perts,
        )
        ctx["pending_scenario"] = scenario.model_dump()

        def _desc(p: Perturbation) -> str:
            if p.kind in ("scale_param", "scale_capacity"):
                return f"{p.kind} {p.target}×{p.factor}"
            if p.kind == "set_param":
                return f"set {p.target}={p.value}"
            if p.kind == "remove_entity":
                return f"remove {p.selector}"
            return f"structural: {p.instruction[:40]}"

        summary = "; ".join(_desc(p) for p in perts)
        return (
            f"Scenario '{scenario.name}' defined ({len(perts)} change(s): {summary}). "
            f"Now call dispatch_scenario to run it against the baseline."
        )

    def _define_sweep(self, ctx: dict, factors=None) -> str:
        """Define a one-factor sensitivity sweep against the session baseline."""
        baseline = ctx["state"].get("optimization_baseline")
        if not baseline:
            return (
                "No baseline optimization exists yet in this session. Run an "
                "optimization first (dispatch_optimization), then define the sweep."
            )
        factors = factors or []
        if not factors:
            return (
                "A sweep needs at least one factor "
                "(e.g. {name:'Demand', target:'demand', low:0.8, high:1.2})."
            )
        norm: list[dict] = []
        for f in factors:
            f = f if isinstance(f, dict) else dict(f)
            if not f.get("target"):
                return f"Sweep factor missing 'target': {f!r}"
            norm.append({
                "name": f.get("name") or f["target"],
                "target": f["target"],
                "low": float(f.get("low", 0.8)),
                "high": float(f.get("high", 1.2)),
                "selector": f.get("selector", {}) or {},
            })
        ctx["pending_sweep"] = {"factors": norm}
        names = ", ".join(f["name"] for f in norm)
        return (
            f"Sensitivity sweep defined over {len(norm)} factor(s): {names}. "
            f"Now call dispatch_sweep to produce the tornado chart."
        )
