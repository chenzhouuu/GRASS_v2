"""LangChain tool wrappers for validated Neo4j access."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.tools import tool

from .cypher_gateway import (
    MAX_RECORDS,
    fix_cypher_deprecations,
    get_cypher_gateway,
    validate_cypher_query,
)

logger = logging.getLogger(__name__)


def _validate_cypher(query: str) -> str | None:
    """Backward-compatible validator used by older tests and helpers."""
    result = validate_cypher_query(query, require_read_only=True)
    return None if result.valid else "; ".join(result.errors)


def _fix_cypher_deprecations(query: str) -> str:
    """Backward-compatible alias for deterministic Cypher cleanup."""
    return fix_cypher_deprecations(query)


@tool
def validate_cypher(
    query: Annotated[str, "The Cypher query to validate before execution."],
) -> Annotated[dict[str, Any], "Validation report with validity, errors, and warnings."]:
    """Validate a Cypher query without executing it.

    Use this before calling ``execute_read_cypher``.  The validator enforces
    GRASS's read-only retrieval policy and checks known labels/relationships.
    """
    return validate_cypher_query(query, require_read_only=True).model_dump()


@tool
def execute_read_cypher(
    query: Annotated[str, "The read-only Cypher query to execute."],
    params: Annotated[dict | None, "Optional query parameters dict."] = None,
) -> Annotated[dict[str, Any], "Result dict with records, error, metadata, and validation."]:
    """Execute a validated read-only Cypher query through the configured gateway."""
    result = get_cypher_gateway().read_cypher(query, params or {})
    if result.error:
        logger.warning("Cypher read failed: %s", result.error)
    else:
        logger.info(
            "Cypher read OK via %s — %d record(s)%s",
            result.source,
            result.row_count,
            " (truncated)" if result.truncated else "",
        )
    return result.to_tool_dict()


@tool
def execute_cypher(
    query: Annotated[str, "The read-only Cypher query to execute."],
    params: Annotated[dict | None, "Optional query parameters dict."] = None,
) -> Annotated[dict[str, Any], "Result dict with records, error, metadata, and validation."]:
    """Backward-compatible read-only Cypher execution tool.

    Existing GRASS code and tests import ``execute_cypher``.  New agent prompts
    should prefer ``execute_read_cypher`` so the read-only contract is explicit.
    """
    return execute_read_cypher.func(query=query, params=params)


@tool
def get_schema() -> Annotated[str, "Formatted Neo4j schema string."]:
    """Return the Neo4j database schema through the configured Cypher gateway."""
    try:
        return get_cypher_gateway().get_schema()
    except Exception as exc:
        logger.error("Failed to retrieve schema: %s", exc)
        return f"Error retrieving schema: {exc}"


__all__ = [
    "MAX_RECORDS",
    "execute_cypher",
    "execute_read_cypher",
    "get_schema",
    "validate_cypher",
]
