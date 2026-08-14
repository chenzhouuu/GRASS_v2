"""Analytics Agent — merged data analysis + visualization agent.

Replaces the separate Code Agent and Visualization Agent. Executes Python
code to analyze data (pandas/scipy/sklearn) AND generate interactive
Plotly charts (serialized as JSON specs for frontend rendering).

Design informed by:
- Microsoft LIDA: template/scaffold pattern, convention-based output capture
- Chat2Plot: structured JSON spec output for safe frontend rendering
- Data-to-Dashboard (KDD 2025): domain-grounded analysis before chart creation

    agent = AnalyticsAgent(model)
    result = agent.invoke(state)
    # result["messages"]          - summary of analysis + charts
    # result["analysis_code"]     - last executed Python code
    # result["analysis_results"]  - stdout text (analysis findings)
    # result["analysis_error"]    - error string or None
    # result["chart_specs"]       - list of Plotly JSON dicts (or None)
"""

import logging
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..tools.python_executor import execute_python, persist_cypher_results
from ..utils.data_summarizer import summarize_data, format_summary_for_prompt, make_data_preview
from ..utils.prompt_loader import load_prompt
from ..utils.plotly_markers import (
    extract_plotly_specs as _extract_plotly_specs_from_text,
    strip_plotly_markers as _strip_plotly_markers_text,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
MAX_SUMMARY_RETRIES = 2


def _coerce_message_content(content: Any) -> str:
    """Flatten LangChain message content into plain text.

    Some models return structured content blocks instead of a single string.
    Extract text blocks so downstream marker parsing always receives text.
    """
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _coerce_message_content(item)
            if text:
                parts.append(text)
        return "".join(parts)
    if isinstance(content, dict):
        parts: list[str] = []
        for key in ("text", "content"):
            if key in content:
                text = _coerce_message_content(content[key])
                if text:
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _extract_plotly_specs(output: Any) -> list[dict]:
    """Extract Plotly JSON specs from output (handles structured content)."""
    return _extract_plotly_specs_from_text(_coerce_message_content(output))


def _strip_plotly_markers(output: Any) -> str:
    """Remove PLOTLY_JSON markers from output (handles structured content)."""
    return _strip_plotly_markers_text(_coerce_message_content(output))


def _classify_error(
    error: str, data_summary: dict, data_path: str = "data/cypher_results.json"
) -> str:
    """Classify execution error and provide targeted fix hints.

    Inspired by PandasAI's error-type-specific correction prompts.
    """
    error_lower = error.lower()

    if "syntaxerror" in error_lower:
        if "unterminated string" in error_lower or "eol while scanning" in error_lower:
            return (
                "SyntaxError from unterminated string. Do NOT use literal newlines "
                "inside f-strings or print() calls. Use \\n for newlines or "
                "string concatenation instead."
            )
        return "Python syntax error. Check for missing colons, parentheses, or indentation."

    if "keyerror" in error_lower or "not in index" in error_lower:
        columns = data_summary.get("field_names", [])
        return f"Column not found. Available columns are: {columns}"

    if "modulenotfounderror" in error_lower or "no module named" in error_lower:
        return (
            "Module not available. Use only: pandas, numpy, plotly, scipy, "
            "sklearn, statsmodels. Do NOT use matplotlib, seaborn, or folium."
        )

    if "typeerror" in error_lower:
        if "numeric_only" in error_lower and "describe" in error_lower:
            return (
                "pandas 2.x removed numeric_only from describe(). "
                "Use df.select_dtypes(include='number').describe() instead."
            )
        if "numeric_only" in error_lower:
            return "Add numeric_only=True to aggregation functions like .mean(), .std(), .sum()."
        return "Type mismatch. Check column dtypes and cast if needed (e.g., pd.to_numeric)."

    if "valueerror" in error_lower:
        return "Value error. Check for empty DataFrames, NaN values, or invalid parameters."

    if "filenotfounderror" in error_lower:
        return f"File not found. Data is at {data_path} — use this exact path."

    if "jsondecodeerror" in error_lower:
        return f"JSON parsing failed. Use pd.read_json('{data_path}') to load data."

    if "timeout" in error_lower:
        return "Execution timed out. Simplify the code — avoid large loops or complex operations."

    return "Review the traceback above and fix the issue."


def _auto_fix_syntax(code: str, error: str) -> str | None:
    """Try to fix known LLM syntax errors deterministically.

    Returns fixed code, or None if the error isn't auto-fixable.
    This avoids burning an LLM retry on mechanical issues like
    unterminated f-strings with literal newlines.
    """
    import re as _re

    error_lower = error.lower()

    # Fix 1: Unterminated f-string with literal newline
    # Pattern: print(f'Data types:\ncounty    str  ← broken across lines
    if "unterminated string literal" in error_lower or "eol while scanning" in error_lower:
        line_match = _re.search(r"line (\d+)", error)
        if not line_match:
            return None
        err_line = int(line_match.group(1)) - 1
        lines = code.split("\n")
        if err_line >= len(lines):
            return None

        line = lines[err_line]
        # Check if this line opens an f-string that doesn't close
        for quote in ('f"', "f'", 'f"""', "f'''"):
            if quote in line:
                close_quote = quote[1:]  # strip 'f' prefix
                # Count open vs close quotes
                after_f = line[line.index(quote) + len(quote):]
                if close_quote not in after_f:
                    # Unterminated — join subsequent lines until we find the close
                    merged = line.rstrip()
                    for j in range(err_line + 1, min(err_line + 5, len(lines))):
                        merged += "\\n" + lines[j].strip()
                        if close_quote in lines[j]:
                            lines[err_line] = merged
                            del lines[err_line + 1: j + 1]
                            return "\n".join(lines)
                    # Couldn't find closing — try just joining next line
                    if err_line + 1 < len(lines):
                        lines[err_line] = line.rstrip() + "\\n" + lines[err_line + 1].lstrip()
                        del lines[err_line + 1]
                        return "\n".join(lines)

    # Fix 2: fig.show() or plt.show() — just comment them out
    if "fig.show()" in code or "plt.show()" in code:
        code = code.replace("fig.show()", "# fig.show() removed")
        code = code.replace("plt.show()", "# plt.show() removed")
        return code

    return None


def _format_tool_message(tool_name: str, tool_result: Any) -> str:
    """Convert raw tool output into a safe ToolMessage payload."""
    if tool_name != "execute_python" or not isinstance(tool_result, dict):
        return str(tool_result)

    parts: list[str] = []
    output = tool_result.get("output")
    error = tool_result.get("error")
    chart_specs = _extract_plotly_specs(output)
    clean_output = _strip_plotly_markers(output)

    if clean_output:
        parts.append(f"output:\n{clean_output}")
    if chart_specs:
        parts.append(f"[{len(chart_specs)} Plotly chart(s) generated]")
    if error:
        parts.append(f"error:\n{error}")

    return "\n\n".join(parts) if parts else "No output."


class AnalyticsAgent:
    """Analytics Agent with tool-calling loop and self-correction.

    Merges the responsibilities of the former Code Agent (data analysis)
    and Visualization Agent (chart generation) into a single worker.

    Parameters
    ----------
    model : BaseChatModel
        A LangChain chat model that supports tool calling.
    """

    agent_name = "analytics_agent"

    def __init__(self, model):
        self.tools = [execute_python]
        self.model = model.bind_tools(self.tools)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run analysis + visualization against *state* data.

        Returns a state-update dict with keys:
            messages, analysis_code, analysis_results, analysis_error,
            chart_specs, past_steps, sender.
        """
        # ── persist upstream data (per-session file) ─────────────
        cypher_results = state.get("cypher_results") or []
        data_path = persist_cypher_results(cypher_results, state.get("session_id"))

        # ── build task description ───────────────────────────────
        task = state.get("worker_task") or (
            "Analyze the data, summarize key findings, and create "
            "appropriate Plotly visualizations."
        )

        # ── build data context (LIDA-inspired summarizer) ────────
        data_summary = summarize_data(cypher_results)
        data_context = format_summary_for_prompt(data_summary)
        raw_preview = make_data_preview(cypher_results, max_rows=3)

        # ── build system prompt ──────────────────────────────────
        template = load_prompt("analytics_agent.txt")
        system_prompt = (
            template
            .replace("{data_summary}", data_context)
            .replace("{data_preview}", raw_preview)
            .replace("{task}", task)
            .replace("{data_path}", data_path)
        )

        # ── assemble conversation ────────────────────────────────
        user_query = state.get("user_query", "")
        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=(
                f"User question: {user_query}\n\n"
                f"Your task: {task}\n\n"
                f"The data ({len(cypher_results)} rows) has been saved to "
                f"{data_path}. Write Python code to analyze "
                f"the data and create Plotly visualizations, then execute "
                f"it using the execute_python tool.\n\n"
                f"Remember: output each Plotly figure using:\n"
                f'print("PLOTLY_JSON::" + pio.to_json(fig) + "::END_PLOTLY_JSON")'
            )),
        ]

        tool_map = {t.name: t for t in self.tools}
        last_code: str | None = None
        last_output: str | None = None
        last_error: str | None = None
        failed_attempts = 0
        max_iterations = 6

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
                    ToolMessage(
                        content=_format_tool_message(tool_name, tool_result),
                        tool_call_id=tc["id"],
                    )
                )

                if tool_name == "execute_python":
                    last_code = tool_args.get("code", "")
                    if isinstance(tool_result, dict):
                        last_output = tool_result.get("output")
                        last_error = tool_result.get("error")
                    else:
                        last_output = None
                        last_error = str(tool_result)

            if last_error:
                # Guardrail: try deterministic auto-fix before burning an LLM retry
                if last_code:
                    fixed_code = _auto_fix_syntax(last_code, last_error)
                    if fixed_code and fixed_code != last_code:
                        logger.info("Auto-fixed syntax error, re-executing without LLM retry")
                        rerun = execute_python.invoke({"code": fixed_code})
                        if isinstance(rerun, dict) and not rerun.get("error"):
                            last_code = fixed_code
                            last_output = rerun.get("output")
                            last_error = None
                            # Replace the error ToolMessage with the success one
                            messages[-1] = ToolMessage(
                                content=_format_tool_message("execute_python", rerun),
                                tool_call_id=messages[-1].tool_call_id,
                            )
                            continue

                failed_attempts += 1
                if failed_attempts > MAX_RETRIES:
                    messages.append(HumanMessage(content=(
                        "Maximum retry budget reached. "
                        "Summarize what you tried and the errors encountered."
                    )))
                    break

                logger.warning(
                    "Analytics attempt %d/%d failed: %s",
                    failed_attempts, MAX_RETRIES + 1, last_error[:200],
                )
                hint = _classify_error(last_error, data_summary, data_path)
                messages.append(HumanMessage(content=(
                    f"Code execution failed:\n{last_error}\n\n"
                    f"Hint: {hint}\n\n"
                    f"Attempt {failed_attempts} of {MAX_RETRIES + 1}. "
                    "Fix the code and try again."
                )))
            else:
                logger.info("Analytics code executed successfully (%d chars output)",
                            len(last_output or ""))

        # ── extract chart specs from stdout BEFORE summary ───────
        # Do this first so we know how many charts were created
        all_output = last_output or ""
        chart_specs = _extract_plotly_specs(all_output)
        analysis_text = _strip_plotly_markers(all_output)

        # ── force summary if needed ──────────────────────────────
        if messages[-1].type != "ai" or messages[-1].tool_calls:
            chart_note = (
                f" {len(chart_specs)} interactive chart(s) were generated and "
                "will be rendered in the frontend automatically."
                if chart_specs else ""
            )
            summary_prompt = (
                "Summarize the analysis results concisely. "
                "State the key findings clearly in plain text."
                f"{chart_note} "
                "Do NOT include any JSON, PLOTLY_JSON markers, or raw chart "
                "data in your summary — the charts are handled separately."
            )
            for _ in range(MAX_SUMMARY_RETRIES):
                messages.append(HumanMessage(content=summary_prompt))
                final_msg = self.model.invoke(messages)
                messages.append(final_msg)
                if not final_msg.tool_calls:
                    break
                summary_prompt = (
                    "Do not call any tools. Reply with a plain-text summary only."
                )

            if messages[-1].tool_calls:
                fallback_summary = analysis_text or (
                    f"Generated {len(chart_specs)} interactive chart(s)."
                    if chart_specs else "Analysis completed."
                )
                messages.append(AIMessage(content=fallback_summary))

        final_content = messages[-1].content if hasattr(messages[-1], "content") else ""

        # Strip any PLOTLY_JSON that leaked into the summary message
        final_content = _strip_plotly_markers(final_content)

        if not chart_specs:
            # Fallback: check final AI message for any inline JSON
            chart_specs = _extract_plotly_specs(
                messages[-1].content if hasattr(messages[-1], "content") else ""
            )

        result: dict[str, Any] = {
            "messages": [AIMessage(content=final_content, name=self.agent_name)],
            "analysis_code": last_code,
            "analysis_results": analysis_text or (
                f"Generated {len(chart_specs)} interactive chart(s)."
                if chart_specs else ""
            ),
            "analysis_error": last_error,
            "chart_specs": chart_specs if chart_specs else None,
            "sender": self.agent_name,
        }

        # ── build past_steps entry ───────────────────────────────
        task_desc = state.get("worker_task", "Analytics")
        if last_error:
            result_summary = f"Error: {last_error}"
        else:
            parts = []
            code_snippet = (last_code or "")[:200]
            output_snippet = (analysis_text or "")[:300]
            parts.append(f"Code: {code_snippet}")
            parts.append(f"Output: {output_snippet}")
            if chart_specs:
                parts.append(f"Charts: {len(chart_specs)} Plotly spec(s)")
            result_summary = "\n".join(parts)
        result["past_steps"] = [(task_desc, result_summary)]

        return result
