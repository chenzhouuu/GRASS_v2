"""Bounded ReAct Cypher agent for GRASS graph retrieval.

The agent keeps GRASS-specific behavior at the boundary: it resolves dairy
entities, validates generated Cypher, executes only read queries, observes
result quality, and returns normalized state updates for downstream agents.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from ..tools.entity_resolver import resolve_entity
from ..tools.neo4j_tools import execute_read_cypher, get_schema, validate_cypher
from ..tools.session_workspace import get_workspace
from ..utils.schema_loader import get_schema as load_schema_text

logger = logging.getLogger(__name__)

PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "prompts", "cypher_agent.txt"
)

MAX_RETRIES = 2
MAX_REACT_ITERATIONS = 8
EXECUTION_TOOL_NAMES = {"execute_read_cypher", "execute_cypher", "read_cypher"}


def _load_prompt_template() -> str:
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


class CypherAgent:
    """Cypher retrieval worker with a bounded ReAct tool loop."""

    agent_name = "cypher_agent"

    def __init__(
        self,
        model,
        schema_text: str | None = None,
        tools: list[BaseTool] | None = None,
    ):
        self.tools = tools or [
            get_schema,
            resolve_entity,
            validate_cypher,
            execute_read_cypher,
        ]
        self.tool_map = {tool.name: tool for tool in self.tools}
        self.schema_text = schema_text or load_schema_text(source="auto")
        self.system_prompt = self._build_system_prompt()
        self.model = model.bind_tools(self.tools)

    def _build_system_prompt(self) -> str:
        template = _load_prompt_template()
        return template.replace("{schema}", self.schema_text)

    def invoke(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run a bounded ReAct retrieval loop and return a GRASS state update."""
        messages = self._prepare_messages(state)
        loop_result = self._run_react_loop(messages)

        # The loop normally ends right after a successful execution (last
        # message is a ToolMessage). The facts the Supervisor needs are all
        # in loop_result — composing them deterministically replaces a
        # full-context LLM call per dispatch (traced: 16.8k prompt tokens
        # for a summary of row count + columns).
        if self._needs_final_summary(messages):
            final_content = self._deterministic_summary(loop_result)
        else:
            final_content = messages[-1].content if hasattr(messages[-1], "content") else ""
        task_desc = self._get_task_desc(state)
        records = loop_result["records"]

        result: dict[str, Any] = {
            "messages": [AIMessage(content=final_content, name=self.agent_name)],
            "cypher_query": loop_result["query"],
            "cypher_results": records,
            "cypher_error": loop_result["error"],
            "cypher_metadata": {
                "source": loop_result["metadata"].get("source"),
                "columns": loop_result["metadata"].get("columns", []),
                "row_count": loop_result["metadata"].get("row_count", len(records)),
                "truncated": loop_result["metadata"].get("truncated", False),
                "read_only_verified": loop_result["metadata"].get(
                    "read_only_verified", False
                ),
                "attempts": loop_result["execution_attempts"],
                "react_trace": loop_result["react_trace"],
                "validation": loop_result["metadata"].get("validation"),
            },
            "sender": self.agent_name,
        }

        # Register the result set as a named workspace table so later
        # Analytics steps can reach data from EVERY retrieval step, not
        # just the last one (P2-a). Without a workspace (no session id:
        # benchmarks, tests) fall back to accumulating the tagged rows in
        # state — the optimizer's legacy data source. Workspace sessions
        # deliberately skip that accumulation: rows would otherwise be
        # rewritten into every checkpoint for the session's lifetime (P2-c).
        workspace = get_workspace(state.get("session_id"))
        if workspace and records:
            table = workspace.register_table(records, description=task_desc[:80])
            result["cypher_metadata"]["workspace_table"] = table["name"]
        else:
            result["all_query_results"] = [
                {**record, "_query_step": task_desc[:80]} for record in records
            ]

        result_summary = self._summarize_step_result(
            loop_result["query"],
            records,
            loop_result["error"],
            final_content,
        )
        if result["cypher_metadata"].get("workspace_table"):
            result_summary += (
                f" [saved as workspace table "
                f"'{result['cypher_metadata']['workspace_table']}']"
            )
        result["past_steps"] = [(task_desc, result_summary)]

        feedback = self._assess_data_quality(records, state)
        if feedback:
            result["worker_feedback"] = feedback

        return result

    def _prepare_messages(self, state: dict[str, Any]) -> list:
        """Build a scoped prompt: system + user request + current task.

        Deliberately does NOT replay the accumulated ``messages`` transcript.
        Under the progress-ledger executor a worker can be re-dispatched several
        times within a single user turn; replaying its own prior summaries
        few-shot-primes the model to reproduce its last query and ignore the new
        instruction (observed in a smoke run: an identical county-count query
        re-emitted for 6+ rounds while the ledger kept asking for a different
        retrieval). Mirrors the Analytics/Optimization workers, which build from
        ``worker_task`` + ``user_query`` rather than the raw history.
        """
        messages: list = [SystemMessage(content=self.system_prompt)]

        user_query = (state.get("user_query") or "").strip()
        worker_task = (state.get("worker_task") or "").strip()

        parts: list[str] = []
        if user_query:
            parts.append(f"User request (overall intent):\n{user_query}")
        if worker_task:
            parts.append(
                "Your current task — execute EXACTLY this retrieval, even if it "
                "differs from earlier queries in the conversation:\n"
                f"{worker_task}"
            )
        if not parts:
            parts.append("Retrieve the data required to answer the user's request.")

        messages.append(HumanMessage(content="\n\n".join(parts)))
        return messages

    def _run_react_loop(self, messages: list) -> dict[str, Any]:
        last_query: str | None = None
        last_records: list[dict] = []
        last_error: str | None = None
        last_metadata: dict[str, Any] = {}
        failed_attempts = 0
        empty_attempts = 0
        execution_attempts = 0
        react_trace: list[dict[str, Any]] = []

        for iteration in range(1, MAX_REACT_ITERATIONS + 1):
            ai_msg = self.model.invoke(messages)
            messages.append(ai_msg)

            tool_calls = getattr(ai_msg, "tool_calls", None) or []
            if not tool_calls:
                break

            had_execution = False
            execution_ok = False

            for tool_call in tool_calls:
                tool_name = tool_call.get("name")
                tool_args = tool_call.get("args", {})
                tool_result = self._invoke_tool(tool_name, tool_args)

                messages.append(
                    ToolMessage(
                        content=self._format_tool_observation(tool_name, tool_result),
                        tool_call_id=tool_call["id"],
                    )
                )

                trace_entry = self._trace_entry(iteration, tool_name, tool_result)
                react_trace.append(trace_entry)

                if tool_name not in EXECUTION_TOOL_NAMES:
                    continue

                had_execution = True
                execution_attempts += 1
                parsed = self._parse_execution_result(tool_args, tool_result)
                records = parsed["records"]
                error = parsed["error"]

                if records or not last_records:
                    last_query = parsed["query"]
                    last_records = records
                    last_error = error
                    last_metadata = parsed["metadata"]

                execution_ok = (not error) and bool(records)

            if not had_execution:
                continue

            if execution_ok:
                logger.info("Cypher returned %d records", len(last_records))
                break

            retry_instruction = self._build_retry_instruction(
                error=last_error,
                records=last_records,
                failed_attempts=failed_attempts,
                empty_attempts=empty_attempts,
            )
            failed_attempts = retry_instruction["failed_attempts"]
            empty_attempts = retry_instruction["empty_attempts"]

            if retry_instruction["message"] is None:
                break

            messages.append(HumanMessage(content=retry_instruction["message"]))
            if retry_instruction["stop"]:
                break

        return {
            "query": last_query,
            "records": last_records,
            "error": last_error,
            "metadata": last_metadata,
            "execution_attempts": execution_attempts,
            "react_trace": react_trace,
        }

    def _invoke_tool(self, tool_name: str | None, tool_args: dict[str, Any]) -> Any:
        if not tool_name:
            return {"error": "Tool call missing name"}

        tool_fn = self.tool_map.get(tool_name)
        if tool_fn is None:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return tool_fn.invoke(tool_args)
        except Exception as exc:
            logger.error("Tool %s failed: %s", tool_name, exc)
            return {"error": str(exc)}

    # 5 rows show the model the result shape and value ranges; row_count and
    # columns are in the metadata. 20 rows of wide records previously put
    # ~20k chars into every post-execution turn.
    MAX_OBSERVATION_RECORDS = 5

    @classmethod
    def _format_tool_observation(cls, tool_name: str | None, tool_result: Any) -> str:
        """Compact large tool outputs before feeding observations back to the LLM."""
        if isinstance(tool_result, dict):
            compact = dict(tool_result)
            records = compact.get("records")
            cap = cls.MAX_OBSERVATION_RECORDS
            if isinstance(records, list) and len(records) > cap:
                compact["records"] = records[:cap]
                compact["records_omitted"] = len(records) - cap
            return json.dumps(compact, default=str)
        return str(tool_result)

    @staticmethod
    def _parse_execution_result(
        tool_args: dict[str, Any],
        tool_result: Any,
    ) -> dict[str, Any]:
        if not isinstance(tool_result, dict):
            return {
                "query": tool_args.get("query"),
                "records": [],
                "error": str(tool_result),
                "metadata": {},
            }

        records = tool_result.get("records") or []
        error = tool_result.get("error")
        metadata = {
            "columns": tool_result.get("columns") or [],
            "row_count": tool_result.get("row_count", len(records)),
            "truncated": tool_result.get("truncated", False),
            "execution_time_ms": tool_result.get("execution_time_ms"),
            "source": tool_result.get("source"),
            "read_only_verified": tool_result.get("read_only_verified", False),
            "validation": tool_result.get("validation"),
        }
        return {
            "query": tool_result.get("query") or tool_args.get("query"),
            "records": records,
            "error": error,
            "metadata": metadata,
        }

    @staticmethod
    def _trace_entry(iteration: int, tool_name: str | None, tool_result: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "iteration": iteration,
            "tool": tool_name or "(missing)",
            "status": "ok",
        }
        if isinstance(tool_result, dict):
            error = tool_result.get("error")
            if error:
                entry["status"] = "error"
                entry["error"] = str(error)[:500]
            if "records" in tool_result:
                entry["row_count"] = len(tool_result.get("records") or [])
            if "valid" in tool_result:
                entry["valid"] = tool_result.get("valid")
                entry["errors"] = tool_result.get("errors", [])
        return entry

    @staticmethod
    def _build_retry_instruction(
        *,
        error: str | None,
        records: list[dict],
        failed_attempts: int,
        empty_attempts: int,
    ) -> dict[str, Any]:
        if not error and not records:
            empty_attempts += 1
            if empty_attempts >= 2:
                return {
                    "failed_attempts": failed_attempts,
                    "empty_attempts": empty_attempts,
                    "stop": True,
                    "message": (
                        "The query executed successfully but returned no results for "
                        "the second time. The data likely does not exist in the "
                        "database, or the task needs clarification. Summarize what "
                        "you searched for and report that no matching records were found."
                    ),
                }
            return {
                "failed_attempts": failed_attempts,
                "empty_attempts": empty_attempts,
                "stop": False,
                "message": (
                    "The query returned no results. Check for entity naming, overly "
                    "restrictive filters, relationship direction, and category terms. "
                    "Use resolve_entity if a name may be ambiguous, then validate and "
                    "try one corrected read-only query."
                ),
            }

        failed_attempts += 1
        if failed_attempts > MAX_RETRIES:
            return {
                "failed_attempts": failed_attempts,
                "empty_attempts": empty_attempts,
                "stop": True,
                "message": (
                    "Maximum retry budget reached. Summarize what you tried, the "
                    "last validation or execution error, and what clarification or "
                    "schema detail would be needed next."
                ),
            }

        return {
            "failed_attempts": failed_attempts,
            "empty_attempts": empty_attempts,
            "stop": False,
            "message": (
                f"The query returned an error: {error}\n"
                f"Failed attempt {failed_attempts} of {MAX_RETRIES + 1}. "
                "Analyze the issue, validate a corrected read-only Cypher query, "
                "then execute it."
            ),
        }

    @staticmethod
    def _needs_final_summary(messages: list) -> bool:
        last_message = messages[-1]
        return last_message.type != "ai" or bool(getattr(last_message, "tool_calls", None))

    @staticmethod
    def _deterministic_summary(loop_result: dict[str, Any]) -> str:
        """Compose the worker's final message from the loop facts."""
        query = loop_result["query"]
        records = loop_result["records"]
        error = loop_result["error"]
        metadata = loop_result["metadata"]

        if error:
            return (
                f"Cypher retrieval failed after "
                f"{loop_result['execution_attempts']} attempt(s): {error}"
            )
        if not records:
            return (
                "Query executed successfully but returned no rows."
                + (f"\nQuery: {query}" if query else "")
            )

        columns = metadata.get("columns") or list(records[0].keys())
        parts = [
            f"Retrieved {len(records)} rows.",
            f"Columns: {', '.join(columns)}.",
        ]
        if metadata.get("truncated"):
            parts.append("Results were truncated at the row cap.")
        if query:
            parts.append(f"Query: {query}")
        return "\n".join(parts)

    def _get_task_desc(self, state: dict[str, Any]) -> str:
        return state.get("worker_task", "Cypher query")

    def _assess_data_quality(
        self,
        records: list[dict],
        state: dict[str, Any],
    ) -> list[dict]:
        """Assess Cypher results for data quality gaps used by the Supervisor."""
        if not records:
            return []

        feedback = []
        columns = set(records[0].keys())
        columns_lower = {c.lower() for c in columns}

        if state.get("requires_geo", False):
            lat_cols = columns_lower & {"lat", "latitude", "origin_lat", "src_lat"}
            lon_cols = columns_lower & {"lon", "lng", "longitude", "origin_lon", "src_lon"}
            dest_lat_cols = columns_lower & {"dest_lat", "dst_lat", "dc_lat", "to_lat"}
            dest_lon_cols = columns_lower & {"dest_lon", "dst_lon", "dc_lon", "to_lon"}

            has_any_coords = bool(lat_cols and lon_cols)
            has_dest_coords = bool(dest_lat_cols and dest_lon_cols)

            if not has_any_coords:
                feedback.append({
                    "type": "data_gap",
                    "agent": "Cypher",
                    "message": "Results lack lat/lon coordinates; map rendering will fail",
                    "columns_present": sorted(columns),
                })
            elif has_any_coords and not has_dest_coords:
                route_indicators = columns_lower & {
                    "origin", "destination", "from", "to",
                    "processor_name", "dc_name", "distribution_center",
                }
                if route_indicators:
                    feedback.append({
                        "type": "data_gap",
                        "agent": "Cypher",
                        "message": (
                            "Results have one coordinate set but route data needs both "
                            "origin and destination coordinates for map rendering"
                        ),
                        "columns_present": sorted(columns),
                    })

        return feedback

    def _summarize_step_result(
        self,
        query: str | None,
        records: list[dict],
        error: str | None,
        final_text: str,
    ) -> str:
        parts = []
        if query:
            parts.append(f"Query: {query}")
        if error:
            parts.append(f"Error: {error}")
        elif records:
            parts.append(f"Returned {len(records)} rows")
            parts.append(f"Columns: {list(records[0].keys())}")
        if final_text:
            text = final_text[:500] if len(final_text) > 500 else final_text
            parts.append(f"Summary: {text}")
        return "\n".join(parts) if parts else "(no output)"
