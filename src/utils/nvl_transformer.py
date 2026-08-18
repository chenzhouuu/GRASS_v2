"""Transform serialized Neo4j query results into NVL-ready graph data."""

from __future__ import annotations

import os
from typing import Any


DEFAULT_MAX_NODES = 250
DEFAULT_MAX_RELATIONSHIPS = 600


def _limit_from_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(0, parsed)


def _caption(properties: dict[str, Any], fallback: str) -> str:
    for key in ("name", "title", "label", "id"):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return fallback


def _clean_properties(value: dict[str, Any], metadata_keys: set[str]) -> dict[str, Any]:
    return {key: val for key, val in value.items() if key not in metadata_keys}


def records_to_nvl_graph(
    records: list[dict[str, Any]],
    *,
    max_nodes: int | None = None,
    max_relationships: int | None = None,
) -> dict[str, Any]:
    """Walk tabular Cypher rows and return a deduplicated NVL graph payload.

    The function consumes the JSON-safe row shape produced by ``to_jsonable``.
    It intentionally tolerates partial graph data because MCP and older cached
    responses may not include relationship endpoint IDs.
    """

    node_limit = (
        _limit_from_env("GRASS_GRAPH_MAX_NODES", DEFAULT_MAX_NODES)
        if max_nodes is None
        else max_nodes
    )
    rel_limit = (
        _limit_from_env("GRASS_GRAPH_MAX_RELS", DEFAULT_MAX_RELATIONSHIPS)
        if max_relationships is None
        else max_relationships
    )

    nodes: dict[str, dict[str, Any]] = {}
    relationships: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    truncated = False

    def add_node(value: dict[str, Any]) -> None:
        nonlocal truncated
        element_id = str(value.get("_element_id") or "")
        if not element_id:
            return
        labels = [str(label) for label in value.get("_labels", [])]
        props = _clean_properties(value, {"_labels", "_element_id"})
        fallback = labels[0] if labels else element_id
        node = {
            "id": element_id,
            "labels": labels,
            "caption": _caption(props, fallback),
            "properties": props,
        }
        if element_id in nodes:
            nodes[element_id] = node
            return
        if len(nodes) >= node_limit:
            truncated = True
            return

        nodes[element_id] = node

    def add_relationship(value: dict[str, Any]) -> None:
        nonlocal truncated
        element_id = str(value.get("_element_id") or "")
        start = value.get("_start_node_id")
        end = value.get("_end_node_id")
        if not element_id or element_id in relationships:
            return
        if start is None or end is None:
            warnings.append(
                f"Relationship {element_id} is missing endpoint IDs and was skipped."
            )
            return
        if len(relationships) >= rel_limit:
            truncated = True
            return

        for endpoint in (str(start), str(end)):
            if endpoint not in nodes:
                if len(nodes) >= node_limit:
                    truncated = True
                    return
                nodes[endpoint] = {
                    "id": endpoint,
                    "labels": [],
                    "caption": endpoint,
                    "properties": {},
                }

        rel_type = str(value.get("_type") or "")
        props = _clean_properties(
            value,
            {"_type", "_element_id", "_start_node_id", "_end_node_id"},
        )
        relationships[element_id] = {
            "id": element_id,
            "from": str(start),
            "to": str(end),
            "type": rel_type,
            "caption": _caption(props, rel_type or element_id),
            "properties": props,
        }

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                visit(item)
            return

        if not isinstance(value, dict):
            return

        if "_labels" in value and "_element_id" in value:
            add_node(value)
        elif "_type" in value and "_element_id" in value:
            add_relationship(value)

        for child in value.values():
            visit(child)

    for record in records:
        visit(record)

    return {
        "nodes": list(nodes.values()),
        "relationships": list(relationships.values()),
        "stats": {
            "nodeCount": len(nodes),
            "relationshipCount": len(relationships),
            "truncated": truncated,
        },
        "warnings": warnings,
    }
