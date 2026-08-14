"""Report Agent — generates a comprehensive PDF supply chain report
using fpdf2, via the execute_python tool.

    agent = ReportAgent(model)
    result = agent.invoke(state)
    # result["messages"]     – summary of the generated report
    # result["report_file"]  – path to the PDF (e.g. "data/report.pdf")
"""

import json
import os
import re
import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..tools.python_executor import execute_python, persist_cypher_results

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "report_agent.txt"
)

MAX_RETRIES = 2


def _load_prompt_template() -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _make_data_preview(records: list[dict], max_rows: int = 5) -> str:
    if not records:
        return "(no data available)"
    preview_rows = records[:max_rows]
    text = json.dumps(preview_rows, indent=2, default=str)
    if len(records) > max_rows:
        text += f"\n... ({len(records)} rows total)"
    return text


def _summarize_cypher(state: dict[str, Any]) -> str:
    query = state.get("cypher_query")
    results = state.get("cypher_results") or []
    error = state.get("cypher_error")

    if error:
        return f"Cypher query failed: {error}"
    if not results:
        return "No Cypher results available."

    lines = [f"Query: {query}", f"Rows returned: {len(results)}"]
    preview = results[:10]
    lines.append(json.dumps(preview, indent=2, default=str))
    if len(results) > 10:
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

    parts = []
    if model_desc:
        parts.append(f"Model: {model_desc}")
    parts.append(json.dumps(solution, indent=2, default=str))
    return "\n".join(parts)


def _summarize_plan(state: dict[str, Any]) -> str:
    plan = state.get("supervisor_plan") or {}
    summary = plan.get("summary", "")
    steps = plan.get("steps", [])
    if not steps:
        return summary or "No plan."
    step_lines = [f"{i}. [{s['agent']}] {s['task']}" for i, s in enumerate(steps, 1)]
    return f"{summary}\nSteps:\n" + "\n".join(step_lines)


def _extract_report_path(output: str) -> str | None:
    """Parse stdout for the REPORT_PATH: tag."""
    for line in output.splitlines():
        match = re.search(r"REPORT_PATH:\s*(\S+)", line)
        if match:
            return match.group(1)
    # Fallback: look for any .pdf path in data/
    for line in output.splitlines():
        matches = re.findall(r"(data/\S+\.pdf)", line)
        if matches:
            return matches[-1]
    return None


class ReportAgent:
    """Report Agent — generates a PDF report via fpdf2.

    Uses the same tool-calling loop pattern as other worker agents.

    Parameters
    ----------
    model : BaseChatModel
        A LangChain chat model that supports tool calling.
    """

    agent_name = "report_agent"

    def __init__(self, model):
        self.tools = [execute_python]
        self.model = model.bind_tools(self.tools)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Generate the PDF report.

        Returns a state-update dict with keys:
            messages, report_file, sender.
        """
        # ── persist upstream data (per-session file) ─────────────
        cypher_results = state.get("cypher_results") or []
        data_path = persist_cypher_results(cypher_results, state.get("session_id"))
        # The PDF goes into the same per-session directory so concurrent
        # sessions cannot overwrite each other's reports; /api/files serves
        # data/outputs/<session>/ by basename.
        report_path = os.path.join(os.path.dirname(data_path), "report.pdf")

        # ── build system prompt ──────────────────────────────────
        template = _load_prompt_template()
        system_prompt = (
            template
            .replace("{user_query}", state.get("user_query", ""))
            .replace("{plan_summary}", _summarize_plan(state))
            .replace("{cypher_summary}", _summarize_cypher(state))
            .replace("{analysis_summary}", _summarize_analysis(state))
            .replace("{viz_summary}", _summarize_viz(state))
            .replace("{optimization_summary}", _summarize_optimization(state))
            .replace("{data_path}", data_path)
            .replace("{report_path}", report_path)
        )

        # ── assemble conversation ────────────────────────────────
        chart_specs = state.get("chart_specs") or []
        viz_note = ""
        if chart_specs:
            viz_note = (
                f"\n\n{len(chart_specs)} Plotly chart(s) were generated. "
                "Summarize chart findings in the report text."
            )

        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"Generate the PDF report for: {state.get('user_query', '')}\n\n"
                f"Data rows available: {len(cypher_results)}\n"
                f"Data file: {data_path}"
                f"{viz_note}\n\n"
                "Write the complete Python script and execute it with "
                "the execute_python tool.  The script must save the PDF "
                f"and print REPORT_PATH: {report_path}"
            )),
        ]

        tool_map = {t.name: t for t in self.tools}
        last_output: str | None = None
        last_error: str | None = None
        failed_attempts = 0
        max_iterations = 10

        for _ in range(max_iterations):
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)

            if not ai_msg.tool_calls:
                break

            for tc in ai_msg.tool_calls:
                tool_name = tc["name"]
                tool_args = tc["args"]
                tool_fn = tool_map.get(tool_name)
                if tool_fn is None:
                    tool_result = f"Unknown tool: {tool_name}"
                else:
                    tool_result = tool_fn.invoke(tool_args)

                messages.append(
                    ToolMessage(content=str(tool_result), tool_call_id=tc["id"])
                )

                if tool_name == "execute_python":
                    if isinstance(tool_result, dict):
                        last_output = tool_result.get("output")
                        last_error = tool_result.get("error")
                    else:
                        last_output = None
                        last_error = str(tool_result)

            if last_error:
                failed_attempts += 1
                if failed_attempts > MAX_RETRIES:
                    messages.append(HumanMessage(content=(
                        "Maximum retry budget reached.  "
                        "Summarize what you attempted and any partial results."
                    )))
                    continue

                logger.warning(
                    "Report attempt %d/%d failed: %s",
                    failed_attempts, MAX_RETRIES + 1, last_error[:200],
                )

                # Detect string quoting errors (common with LLM-generated code)
                quote_hint = ""
                if "SyntaxError" in last_error or "EOL while scanning" in last_error:
                    quote_hint = (
                        "\n\nIMPORTANT: This looks like a string quoting error. "
                        "Use DOUBLE QUOTES for all text strings in pdf.multi_cell() "
                        "and pdf.cell() calls.  Build text in variables first, e.g.:\n"
                        '  text = "Lancaster County\'s dairy sector has 380 companies."\n'
                        "  pdf.multi_cell(0, 6, text)\n"
                        "Never put raw apostrophes or single quotes inside '...' strings."
                    )

                messages.append(HumanMessage(content=(
                    f"Code execution failed:\n{last_error}\n\n"
                    f"Attempt {failed_attempts} of {MAX_RETRIES + 1}. "
                    f"Fix the code and try again.{quote_hint}"
                )))
            else:
                logger.info("Report PDF generated successfully")

        # ── force summary if needed ──────────────────────────────
        if messages[-1].type != "ai" or messages[-1].tool_calls:
            messages.append(HumanMessage(content=(
                "Summarize the report you generated.  "
                "State the file path."
            )))
            final_msg = self.model.invoke(messages)
            messages.append(final_msg)

        final_content = (
            messages[-1].content if hasattr(messages[-1], "content") else ""
        )

        # ── extract report path ──────────────────────────────────
        report_file = _extract_report_path(last_output or "")
        if not report_file:
            report_file = _extract_report_path(final_content)

        if report_file:
            logger.info("Report saved to: %s", report_file)
        else:
            logger.warning("Could not extract report file path from output")

        return {
            "messages": [AIMessage(content=final_content, name=self.agent_name)],
            "report_file": report_file,
            "sender": self.agent_name,
        }
