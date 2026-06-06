"""Load and format the Neo4j schema for use in agent prompts.

Supports two sources:
1. Live introspection from the connected Neo4j database (default).
2. A static YAML file at config/neo4j_schema.yaml (fallback / override).

The formatted output is a human-readable string suitable for injecting
into an LLM system prompt so the Cypher Agent knows what nodes,
relationships, and properties are available.
"""

import os
import logging

import yaml

from .neo4j_connection import get_session

logger = logging.getLogger(__name__)

SCHEMA_YAML_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "neo4j_schema.yaml"
)


# ── live introspection ──────────────────────────────────────────────

def _fetch_node_labels_and_props(session) -> list[dict]:
    """Return [{label, properties: [name, type]}] from the live database."""
    result = session.run("CALL db.schema.nodeTypeProperties()")
    label_props: dict[str, list[dict]] = {}
    for record in result:
        labels = record["nodeLabels"]
        for label in labels:
            if label not in label_props:
                label_props[label] = []
            prop = record["propertyName"]
            ptype = record["propertyTypes"]
            if prop:
                entry = {"name": prop, "types": ptype}
                if entry not in label_props[label]:
                    label_props[label].append(entry)
    return [
        {"label": label, "properties": props}
        for label, props in sorted(label_props.items())
    ]


def _fetch_relationship_types_and_props(session) -> list[dict]:
    """Return [{type, properties: [name, type]}] from the live database."""
    result = session.run("CALL db.schema.relTypeProperties()")
    rel_props: dict[str, list[dict]] = {}
    for record in result:
        rel_type = record["relType"]
        # relType comes back as ":`TYPE_NAME`"
        rel_type = rel_type.strip(":` ")
        if rel_type not in rel_props:
            rel_props[rel_type] = []
        prop = record["propertyName"]
        ptype = record["propertyTypes"]
        if prop:
            entry = {"name": prop, "types": ptype}
            if entry not in rel_props[rel_type]:
                rel_props[rel_type].append(entry)
    return [
        {"type": rel_type, "properties": props}
        for rel_type, props in sorted(rel_props.items())
    ]


def _fetch_relationship_patterns(session) -> list[dict]:
    """Return [{"source": "Label", "type": "REL", "target": "Label"}].

    This tells the LLM exactly which node labels each relationship
    type connects, so it can write correct traversal patterns.
    """
    result = session.run(
        "MATCH (a)-[r]->(b) "
        "WITH labels(a)[0] AS src, type(r) AS rel, labels(b)[0] AS tgt "
        "RETURN DISTINCT src, rel, tgt ORDER BY src, rel, tgt"
    )
    return [
        {"source": rec["src"], "type": rec["rel"], "target": rec["tgt"]}
        for rec in result
    ]


def fetch_schema_from_db() -> dict:
    """Introspect the live Neo4j database and return a schema dict."""
    with get_session() as session:
        nodes = _fetch_node_labels_and_props(session)
        relationships = _fetch_relationship_types_and_props(session)
        patterns = _fetch_relationship_patterns(session)
    return {"nodes": nodes, "relationships": relationships, "patterns": patterns}


# ── static YAML ─────────────────────────────────────────────────────

def load_schema_from_yaml(path: str | None = None) -> dict:
    """Load schema from a YAML file. Returns dict with nodes/relationships."""
    path = path or SCHEMA_YAML_PATH
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── formatting ──────────────────────────────────────────────────────

def format_schema(schema: dict) -> str:
    """Format a schema dict into a readable string for LLM prompts.

    Example output:
        Node labels:
          - Company (name: String, revenue: Float, ...)
          - Location (latitude: Float, longitude: Float, ...)

        Relationship types:
          - SUPPLIES (volume: Integer, ...)
          - LOCATED_IN ()
    """
    lines: list[str] = []

    lines.append("Node labels:")
    for node in schema.get("nodes", []):
        props = ", ".join(
            f"{p['name']}: {p.get('types', p.get('type', ''))}"
            for p in node.get("properties", [])
        )
        label = node.get("label", "?")
        lines.append(f"  - {label} ({props})" if props else f"  - {label}")

    lines.append("")
    lines.append("Relationship types:")
    for rel in schema.get("relationships", []):
        props = ", ".join(
            f"{p['name']}: {p.get('types', p.get('type', ''))}"
            for p in rel.get("properties", [])
        )
        rel_type = rel.get("type", "?")
        lines.append(f"  - {rel_type} ({props})" if props else f"  - {rel_type}")

    patterns = schema.get("patterns", [])
    if patterns:
        lines.append("")
        lines.append("Graph patterns (how nodes connect):")
        for p in patterns:
            lines.append(
                f"  (:{p['source']})-[:{p['type']}]->(:{p['target']})"
            )

    return "\n".join(lines)


# ── public API ──────────────────────────────────────────────────────

def get_schema(source: str = "auto") -> str:
    """Return a formatted schema string.

    Args:
        source: "db" for live introspection, "yaml" for static file,
                "auto" tries db first then falls back to yaml.
    """
    if source == "yaml":
        schema = load_schema_from_yaml()
    elif source == "db":
        schema = fetch_schema_from_db()
    else:  # auto
        try:
            schema = fetch_schema_from_db()
            logger.info("Schema loaded from live database")
        except Exception as exc:
            logger.warning("Live schema fetch failed (%s), falling back to YAML", exc)
            if os.path.exists(SCHEMA_YAML_PATH):
                schema = load_schema_from_yaml()
                logger.info("Schema loaded from %s", SCHEMA_YAML_PATH)
            else:
                raise RuntimeError(
                    f"Cannot load schema: DB introspection failed and "
                    f"{SCHEMA_YAML_PATH} not found"
                ) from exc

    return format_schema(schema)
