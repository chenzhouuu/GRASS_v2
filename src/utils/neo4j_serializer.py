"""Shared Neo4j value serializer for JSON-safe conversion.

Used by both chat.py (SSE events) and database.py (query results).
"""

from typing import Any


def to_jsonable(value: Any) -> Any:
    """Recursively convert Neo4j values to JSON-serializable primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}

    # Neo4j Node / Relationship objects
    if hasattr(value, "items"):
        try:
            props = {str(k): to_jsonable(v) for k, v in dict(value.items()).items()}
        except Exception:
            props = {}
        if hasattr(value, "labels"):
            props["_labels"] = sorted(list(value.labels))
        if hasattr(value, "type"):
            props["_type"] = str(value.type)
        if hasattr(value, "element_id"):
            props["_element_id"] = str(value.element_id)
        return props

    # Neo4j Path objects
    if hasattr(value, "nodes") and hasattr(value, "relationships"):
        try:
            return {
                "nodes": [to_jsonable(n) for n in value.nodes],
                "relationships": [to_jsonable(r) for r in value.relationships],
            }
        except Exception:
            pass

    return str(value)
