"""Validated Cypher access layer for GRASS.

The Cypher agent should reason about graph-retrieval tasks, not about how
Neo4j is reached.  This module provides that boundary:

* a stable result/validation contract for the rest of GRASS,
* a direct Neo4j-driver backend used by the current application,
* an optional Neo4j MCP backend selected by configuration.

Both backends enforce read-only execution before any query reaches Neo4j.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Literal, Protocol

from pydantic import BaseModel, Field

from ..utils.neo4j_connection import get_neo4j_config, get_session
from ..utils.neo4j_serializer import to_jsonable
from ..utils.schema_loader import get_schema as load_schema_text

logger = logging.getLogger(__name__)

MAX_RECORDS = 10000


class CypherValidationResult(BaseModel):
    """Pre-execution policy and schema validation result."""

    query: str
    normalized_query: str
    valid: bool
    read_only: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    requires_approval: bool = False


class CypherExecutionResult(BaseModel):
    """Normalized result shape for Cypher execution."""

    query: str
    params: dict[str, Any] = Field(default_factory=dict)
    records: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: int | None = None
    error: str | None = None
    source: Literal["direct", "mcp"] = "direct"
    read_only_verified: bool = False
    validation: CypherValidationResult | None = None

    def to_tool_dict(self) -> dict[str, Any]:
        """Return the compact dict shape expected by LangChain tools and tests."""
        return {
            "records": self.records,
            "error": self.error,
            "query": self.query,
            "params": self.params,
            "columns": self.columns,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "execution_time_ms": self.execution_time_ms,
            "source": self.source,
            "read_only_verified": self.read_only_verified,
            "validation": (
                self.validation.model_dump() if self.validation is not None else None
            ),
        }


class CypherGateway(Protocol):
    """Stable boundary for graph schema lookup and read-only Cypher execution."""

    source: Literal["direct", "mcp"]

    def get_schema(self) -> str:
        """Return a formatted Neo4j schema string."""

    def read_cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> CypherExecutionResult:
        """Validate and execute a read-only Cypher query."""


_schema_cache: dict[str, set[str]] | None = None
_gateway_singleton: CypherGateway | None = None
_gateway_backend: str | None = None


def reset_cypher_gateway_cache() -> None:
    """Reset cached gateway/schema state after runtime Neo4j config changes."""
    global _schema_cache, _gateway_singleton, _gateway_backend
    _schema_cache = None
    _gateway_singleton = None
    _gateway_backend = None


def _strip_comments_and_string_literals(query: str) -> str:
    """Remove strings/comments so policy regexes inspect Cypher structure only."""
    without_block_comments = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    without_line_comments = re.sub(r"//.*?$", " ", without_block_comments, flags=re.MULTILINE)
    return re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", without_line_comments)


def fix_cypher_deprecations(query: str) -> str:
    """Apply deterministic compatibility fixes for common Neo4j 5.x syntax issues."""
    query = re.sub(
        r"(?<!point\.)distance\s*\(\s*point\s*\(",
        "point.distance(point(",
        query,
    )
    return re.sub(r"point\((\w+\.location)\)", r"\1", query)


def _load_schema_cache() -> dict[str, set[str]]:
    """Load and cache known labels/relationship types for lightweight validation."""
    global _schema_cache
    if _schema_cache is not None:
        return _schema_cache

    labels: set[str] = set()
    rel_types: set[str] = set()
    try:
        schema = load_schema_text(source="auto")
        for line in schema.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") and "(" in stripped:
                name = stripped[2:].split("(")[0].strip()
                if name and not name.startswith("("):
                    labels.add(name)
            elif stripped.startswith("(:"):
                for match in re.findall(r":(\w+)", stripped):
                    if match.isupper() or "_" in match:
                        rel_types.add(match)
                    else:
                        labels.add(match)
    except Exception:
        logger.debug("Schema cache unavailable during Cypher validation", exc_info=True)

    _schema_cache = {"labels": labels, "rel_types": rel_types}
    return _schema_cache


def _has_result_bound(query_without_literals: str) -> bool:
    """Return true when a query has LIMIT or is naturally bounded by aggregation."""
    upper = query_without_literals.upper()
    if re.search(r"\bLIMIT\s+\d+\b", upper):
        return True
    return bool(
        re.search(
            r"\b(COUNT|SUM|AVG|MIN|MAX|COLLECT|PERCENTILECONT|PERCENTILEDISC|STDEV)\s*\(",
            upper,
        )
    )


def validate_cypher_query(
    query: str,
    *,
    require_read_only: bool = True,
) -> CypherValidationResult:
    """Validate syntax/policy constraints before executing generated Cypher."""
    normalized_query = fix_cypher_deprecations(query.strip())
    errors: list[str] = []
    warnings: list[str] = []

    if not normalized_query:
        errors.append("Empty query string")
        return CypherValidationResult(
            query=query,
            normalized_query=normalized_query,
            valid=False,
            read_only=False,
            errors=errors,
        )

    for open_ch, close_ch, name in [
        ("(", ")", "parentheses"),
        ("[", "]", "brackets"),
        ("{", "}", "braces"),
    ]:
        if normalized_query.count(open_ch) != normalized_query.count(close_ch):
            errors.append(
                f"Unbalanced {name}: {normalized_query.count(open_ch)} open vs "
                f"{normalized_query.count(close_ch)} close"
            )

    structural_query = _strip_comments_and_string_literals(normalized_query)
    upper = structural_query.upper()

    forbidden_patterns = [
        r"\bDETACH\s+DELETE\b",
        r"\bCREATE\b",
        r"\bMERGE\b",
        r"\bSET\b",
        r"\bDELETE\b",
        r"\bREMOVE\b",
        r"\bDROP\b",
        r"\bALTER\b",
        r"\bRENAME\b",
        r"\bGRANT\b",
        r"\bDENY\b",
        r"\bREVOKE\b",
        r"\bLOAD\s+CSV\b",
        r"\bFOREACH\b",
        r"\bPROFILE\b",
        r"\bUSE\b",
        r"\bSHOW\s+(USERS|DATABASES|ROLES|PRIVILEGES|SERVERS|TRANSACTIONS|SETTINGS)\b",
        r"\bTERMINATE\b",
        r"\bSTART\s+DATABASE\b",
        r"\bSTOP\s+DATABASE\b",
        r"\bCALL\s+DBMS\.",
        r"\bCALL\s+DB\.(CREATE|DROP|INDEX\.FULLTEXT\.CREATE|AWAIT|RESAMPLE)",
        r"\bCALL\s+APOC\.(CREATE|MERGE|REFACTOR|PERIODIC|LOAD|EXPORT|TRIGGER)",
    ]
    read_only = not any(re.search(pattern, upper) for pattern in forbidden_patterns)
    if require_read_only and not read_only:
        errors.append("Only read-only Cypher is allowed for GRASS data retrieval")

    cache = _load_schema_cache()
    if cache["labels"]:
        for label in re.findall(r"\(\w*:`?(\w+)`?", structural_query):
            if label and label[0].isupper() and label not in cache["labels"]:
                errors.append(
                    f"Unknown node label '{label}'. Known labels: {sorted(cache['labels'])}"
                )
        for rel_type in re.findall(r"\[:`?(\w+)`?", structural_query):
            if rel_type and rel_type not in cache["rel_types"]:
                errors.append(
                    f"Unknown relationship type '{rel_type}'. "
                    f"Known types: {sorted(cache['rel_types'])}"
                )

    requires_approval = not _has_result_bound(structural_query)
    if requires_approval:
        warnings.append(
            "Query has no LIMIT and is not an aggregation; results may be truncated"
        )

    return CypherValidationResult(
        query=query,
        normalized_query=normalized_query,
        valid=not errors,
        read_only=read_only,
        errors=errors,
        warnings=warnings,
        requires_approval=requires_approval,
    )


class DirectNeo4jGateway:
    """Cypher gateway backed by the local Neo4j Python driver."""

    source: Literal["direct"] = "direct"

    def get_schema(self) -> str:
        return load_schema_text(source="auto")

    def read_cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> CypherExecutionResult:
        params = params or {}
        validation = validate_cypher_query(query, require_read_only=True)
        if not validation.valid:
            return CypherExecutionResult(
                query=validation.normalized_query,
                params=params,
                error="Validation error: " + "; ".join(validation.errors),
                source=self.source,
                read_only_verified=validation.read_only,
                validation=validation,
            )

        try:
            import time

            start_time = time.time()
            records: list[dict[str, Any]] = []
            truncated = False

            with get_session() as session:

                def _run_read(tx):
                    nonlocal truncated
                    result = tx.run(validation.normalized_query, parameters=params)
                    rows: list[dict[str, Any]] = []
                    for idx, record in enumerate(result):
                        if idx >= MAX_RECORDS:
                            truncated = True
                            break
                        rows.append(to_jsonable(dict(record)))
                    return rows

                records = session.execute_read(_run_read)

            execution_time_ms = int((time.time() - start_time) * 1000)
            columns = list(records[0].keys()) if records else []
            return CypherExecutionResult(
                query=validation.normalized_query,
                params=params,
                records=records,
                columns=columns,
                row_count=len(records),
                truncated=truncated,
                execution_time_ms=execution_time_ms,
                source=self.source,
                read_only_verified=True,
                validation=validation,
            )
        except Exception as exc:
            logger.error("Cypher execution failed: %s", exc)
            return CypherExecutionResult(
                query=validation.normalized_query,
                params=params,
                error=str(exc),
                source=self.source,
                read_only_verified=True,
                validation=validation,
            )


def _run_async(factory: Callable[[], Any]) -> Any:
    """Run async MCP calls from sync code without assuming an event-loop context."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


class McpNeo4jGateway:
    """Cypher gateway backed by Neo4j's MCP server.

    This backend is optional.  It is selected with ``GRASS_CYPHER_BACKEND=mcp``
    and requires ``langchain-mcp-adapters`` plus ``neo4j-mcp-server``.
    """

    source: Literal["mcp"] = "mcp"

    def __init__(self) -> None:
        self._tools: dict[str, Any] | None = None

    def _server_config(self) -> dict[str, Any]:
        neo4j_config = get_neo4j_config()
        command = os.getenv("GRASS_NEO4J_MCP_COMMAND", "python")
        args = shlex.split(
            os.getenv("GRASS_NEO4J_MCP_ARGS", "-m neo4j_mcp_server")
        )
        return {
            "neo4j": {
                "transport": "stdio",
                "command": command,
                "args": args,
                "env": {
                    "NEO4J_URI": neo4j_config["uri"],
                    "NEO4J_USERNAME": neo4j_config["username"],
                    "NEO4J_PASSWORD": neo4j_config["password"],
                    "NEO4J_DATABASE": neo4j_config["database"],
                    "NEO4J_READ_ONLY": "true",
                    "NEO4J_TELEMETRY": "false",
                },
            }
        }

    def _load_tools(self) -> dict[str, Any]:
        if self._tools is not None:
            return self._tools

        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise RuntimeError(
                "MCP Cypher backend requires langchain-mcp-adapters. "
                "Install project requirements and set GRASS_CYPHER_BACKEND=mcp."
            ) from exc

        async def _get_tools():
            client = MultiServerMCPClient(self._server_config())
            tools = await client.get_tools()
            return {tool.name: tool for tool in tools}

        self._tools = _run_async(_get_tools)
        return self._tools

    def _find_tool(self, preferred_name: str, required_terms: tuple[str, ...]) -> Any:
        tools = self._load_tools()
        if preferred_name in tools:
            return tools[preferred_name]

        for name, tool in tools.items():
            normalized = name.lower().replace("_", "-")
            if all(term in normalized for term in required_terms):
                return tool

        raise RuntimeError(
            f"Neo4j MCP tool not found. Wanted '{preferred_name}' or a name "
            f"containing {required_terms}; available tools: {sorted(tools)}"
        )

    @staticmethod
    def _normalize_mcp_payload(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
        if isinstance(payload, dict):
            if payload.get("error"):
                return [], str(payload["error"])
            records = payload.get("records") or payload.get("results") or payload.get("data")
            if isinstance(records, list):
                return [to_jsonable(dict(row)) for row in records if isinstance(row, dict)], None
            if "content" in payload:
                return McpNeo4jGateway._normalize_mcp_payload(payload["content"])

        if isinstance(payload, list):
            if payload and all(isinstance(row, dict) for row in payload):
                return [to_jsonable(dict(row)) for row in payload], None
            text_parts = []
            for item in payload:
                if isinstance(item, dict) and "text" in item:
                    text_parts.append(str(item["text"]))
                elif hasattr(item, "text"):
                    text_parts.append(str(item.text))
            if text_parts:
                return McpNeo4jGateway._normalize_mcp_payload("\n".join(text_parts))

        if isinstance(payload, str):
            text = payload.strip()
            if not text:
                return [], None
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return [], text
            return McpNeo4jGateway._normalize_mcp_payload(parsed)

        return [], None

    def get_schema(self) -> str:
        tool_name = os.getenv("GRASS_NEO4J_MCP_SCHEMA_TOOL", "get-schema")
        tool = self._find_tool(tool_name, ("schema",))

        async def _call():
            return await tool.ainvoke({})

        payload = _run_async(_call)
        if isinstance(payload, str):
            return payload
        records, error = self._normalize_mcp_payload(payload)
        if error:
            return error
        return json.dumps(records, indent=2, default=str)

    def read_cypher(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> CypherExecutionResult:
        params = params or {}
        validation = validate_cypher_query(query, require_read_only=True)
        if not validation.valid:
            return CypherExecutionResult(
                query=validation.normalized_query,
                params=params,
                error="Validation error: " + "; ".join(validation.errors),
                source=self.source,
                read_only_verified=validation.read_only,
                validation=validation,
            )

        tool_name = os.getenv("GRASS_NEO4J_MCP_READ_TOOL", "read-cypher")
        try:
            tool = self._find_tool(tool_name, ("read", "cypher"))

            async def _call():
                payload = {"query": validation.normalized_query}
                if params:
                    payload["params"] = params
                return await tool.ainvoke(payload)

            payload = _run_async(_call)
            records, error = self._normalize_mcp_payload(payload)
            truncated = len(records) > MAX_RECORDS
            if truncated:
                records = records[:MAX_RECORDS]
            columns = list(records[0].keys()) if records else []
            return CypherExecutionResult(
                query=validation.normalized_query,
                params=params,
                records=records,
                columns=columns,
                row_count=len(records),
                truncated=truncated,
                error=error,
                source=self.source,
                read_only_verified=True,
                validation=validation,
            )
        except Exception as exc:
            logger.error("MCP Cypher execution failed: %s", exc)
            return CypherExecutionResult(
                query=validation.normalized_query,
                params=params,
                error=str(exc),
                source=self.source,
                read_only_verified=True,
                validation=validation,
            )


def get_cypher_gateway(backend: str | None = None) -> CypherGateway:
    """Return the configured Cypher gateway singleton."""
    global _gateway_backend, _gateway_singleton

    selected = (backend or os.getenv("GRASS_CYPHER_BACKEND", "direct")).lower()
    if _gateway_singleton is not None and _gateway_backend == selected:
        return _gateway_singleton

    if selected == "mcp":
        _gateway_singleton = McpNeo4jGateway()
    elif selected == "direct":
        _gateway_singleton = DirectNeo4jGateway()
    else:
        raise ValueError(
            f"Unsupported GRASS_CYPHER_BACKEND='{selected}'. Use 'direct' or 'mcp'."
        )

    _gateway_backend = selected
    return _gateway_singleton
