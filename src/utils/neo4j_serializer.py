"""Shared Neo4j value serializer for JSON-safe conversion.

Used by both chat.py (SSE events) and database.py (query results).
"""

from typing import Any


def _safe_element_id(value: Any) -> str | None:
    element_id = getattr(value, "element_id", None)
    if element_id is not None:
        return str(element_id)
    legacy_id = getattr(value, "id", None)
    if legacy_id is not None:
        return str(legacy_id)
    return None


def _relationship_endpoint_id(value: Any, attr_name: str, legacy_name: str) -> str | None:
    endpoint = getattr(value, attr_name, None)
    endpoint_id = _safe_element_id(endpoint) if endpoint is not None else None
    if endpoint_id is not None:
        return endpoint_id

    direct = getattr(value, f"{attr_name}_element_id", None)
    if direct is not None:
        return str(direct)

    legacy = getattr(value, legacy_name, None)
    if legacy is not None:
        return str(legacy)
    return None


def to_jsonable(value: Any) -> Any:
    """Recursively convert Neo4j values to JSON-serializable primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "iso_format"):
        try:
            return value.iso_format()
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if hasattr(value, "latitude") and hasattr(value, "longitude"):
        try:
            return {
                "latitude": float(value.latitude),
                "longitude": float(value.longitude),
            }
        except Exception:
            pass
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "srid"):
        try:
            point = {"x": float(value.x), "y": float(value.y), "srid": value.srid}
            if hasattr(value, "z"):
                point["z"] = float(value.z)
            return point
        except Exception:
            pass
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
            start_id = _relationship_endpoint_id(value, "start_node", "start_node_id")
            end_id = _relationship_endpoint_id(value, "end_node", "end_node_id")
            if start_id is not None:
                props["_start_node_id"] = start_id
            if end_id is not None:
                props["_end_node_id"] = end_id
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
