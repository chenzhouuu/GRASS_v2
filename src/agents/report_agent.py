"""Report Agent — generates a PDF supply chain report.

The LLM authors ONLY the narrative content (structured output:
ReportContent); the PDF layout is rendered by fixed code in
src/tools/report_renderer.py. This replaces the previous design where
the LLM wrote a full fpdf2 script per attempt — a traced run burned
three ~6k-token script regenerations on an indentation error, a missing
import, and a layout crash, and still delivered no PDF.

    agent = ReportAgent(model)
    result = agent.invoke(state)
    # result["messages"]     – summary of the generated report
    # result["report_file"]  – path to the PDF (e.g. "data/outputs/<sid>/report.pdf")
"""

import json
import logging
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from ..core.schemas import ReportContent
from ..tools import python_executor
from ..tools.report_renderer import render_report_pdf

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "report_agent.txt"
)

MAX_CONTENT_ATTEMPTS = 2


def _load_prompt_template() -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _summarize_cypher(state: dict[str, Any]) -> str:
    query = state.get("cypher_query")
    results = state.get("cypher_results") or []
    error = state.get("cypher_error")

    if error:
        return f"Cypher query failed: {error}"
    if not results:
        return "No Cypher results available."

    # 3 rows show shape and value ranges; tables in the PDF are rendered
    # deterministically, so raw rows in the prompt only cost tokens.
    lines = [f"Query: {query}", f"Rows returned: {len(results)}"]
    preview = results[:3]
    lines.append(json.dumps(preview, indent=2, default=str))
    if len(results) > 3:
        lines.append(f"... ({len(results)} rows total)")
    return "\n".join(lines)


def _summarize_analysis(state: dict[str, Any]) -> str:
    output = state.get("analysis_results")
    error = state.get("analysis_error")

    if error:
        return f"Analysis failed: {error}"
    if not output:
        return "No analysis results available."
    if len(output) > 3000:
        return output[:3000] + "\n... (truncated)"
    return output


def _summarize_viz(state: dict[str, Any]) -> str:
    chart_specs = state.get("chart_specs") or []
    geo_data = state.get("geo_data") or {}

    parts = []
    if chart_specs:
        parts.append(f"{len(chart_specs)} interactive Plotly chart(s) generated")
    geo_features = geo_data.get("features", []) if isinstance(geo_data, dict) else []
    if geo_features:
        parts.append(f"Map: {len(geo_features)} geographic features extracted")
    if not parts:
        return "No visualizations generated."
    return "\n".join(parts)


def _summarize_optimization(state: dict[str, Any]) -> str:
    solution = state.get("optimization_solution")
    model_desc = state.get("optimization_model")
    error = state.get("optimization_error")

    if error:
        return f"Optimization failed: {error}"
    if not solution:
        return "No optimization was performed."
    if not isinstance(solution, dict):
        return str(solution)[:2000]

    # Headline figures + top routes give the narrative its exact numbers;
    # the route table in the PDF is rendered deterministically from state.
    parts = []
    if model_desc:
        parts.append(f"Model: {model_desc}")
    for key in ("status", "objective", "solver"):
        if key in solution:
            parts.append(f"{key}: {solution[key]}")
    routes = solution.get("routes") or []
    if isinstance(routes, list) and routes:
        parts.append(f"Active routes: {len(routes)}. First 5:")
        parts.append(json.dumps(routes[:5], indent=2, default=str))
    for key in ("kpis", "binding", "assumptions"):
        if solution.get(key):
            parts.append(f"{key}: {json.dumps(solution[key], default=str)[:600]}")
    return "\n".join(parts)


def _summarize_plan(state: dict[str, Any]) -> str:
    plan = state.get("supervisor_plan") or {}
    summary = plan.get("summary", "")
    steps = plan.get("steps", [])
    if not steps:
        return summary or "No plan."
    step_lines = [f"{i}. [{s['agent']}] {s['task']}" for i, s in enumerate(steps, 1)]
    return f"{summary}\nSteps:\n" + "\n".join(step_lines)


class ReportAgent:
    """Report Agent — LLM-authored content, deterministically rendered PDF.

    Parameters
    ----------
    model : BaseChatModel
        A LangChain chat model that supports structured output.
    """

    agent_name = "report_agent"

    def __init__(self, model):
        self.model = model

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Generate the PDF report.

        Returns a state-update dict with keys:
            messages, report_file, sender.
        """
        # The PDF goes into the per-session directory so concurrent
        # sessions cannot overwrite each other's reports; /api/files serves
        # data/outputs/<session>/ by basename.
        session_id = state.get("session_id")
        rel_report_path = os.path.join(
            os.path.dirname(python_executor.cypher_results_path(session_id)),
            "report.pdf",
        )
        abs_report_path = os.path.join(python_executor.PROJECT_ROOT, rel_report_path)

        template = _load_prompt_template()
        system_prompt = (
            template
            .replace("{user_query}", state.get("user_query", ""))
            .replace("{plan_summary}", _summarize_plan(state))
            .replace("{cypher_summary}", _summarize_cypher(state))
            .replace("{analysis_summary}", _summarize_analysis(state))
            .replace("{viz_summary}", _summarize_viz(state))
            .replace("{optimization_summary}", _summarize_optimization(state))
        )

        data_rows = len(state.get("cypher_results") or [])
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"Write the report content for: {state.get('user_query', '')}\n\n"
                f"Data rows available: {data_rows}"
            )),
        ]

        structured_model = self.model.with_structured_output(ReportContent)
        content: ReportContent | None = None
        last_exc: Exception | None = None
        for attempt in range(MAX_CONTENT_ATTEMPTS):
            try:
                content = structured_model.invoke(messages)
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "Report content attempt %d/%d failed: %s",
                    attempt + 1, MAX_CONTENT_ATTEMPTS, exc,
                )

        if content is None:
            return {
                "messages": [AIMessage(
                    content=f"Report content generation failed: {last_exc}",
                    name=self.agent_name,
                )],
                "report_file": None,
                "sender": self.agent_name,
            }

        try:
            render_report_pdf(content, state, abs_report_path)
        except Exception as exc:
            logger.exception("Report rendering failed")
            return {
                "messages": [AIMessage(
                    content=f"Report rendering failed: {exc}",
                    name=self.agent_name,
                )],
                "report_file": None,
                "sender": self.agent_name,
            }

        section_list = ", ".join(s.heading for s in content.sections)
        final_content = (
            f"PDF report generated: {rel_report_path}\n\n"
            f"**{content.title}**\n\n"
            f"{content.executive_summary}\n\n"
            f"Sections: {section_list}"
        )
        logger.info("Report saved to: %s", rel_report_path)

        return {
            "messages": [AIMessage(content=final_content, name=self.agent_name)],
            "report_file": rel_report_path,
            "sender": self.agent_name,
        }
