"""Schema introspection for the dashboard technical layer."""

import logging
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..tools.cypher_gateway import CypherExecutionResult, get_cypher_gateway
from ..utils.neo4j_connection import get_neo4j_runtime_state
from ..utils.nvl_transformer import records_to_nvl_graph
from .models import DashboardConnection

logger = logging.getLogger(__name__)

PATTERN_SAMPLE_LIMIT = 10000


class DashboardStats(BaseModel):
    nodeCount: int = 0
    relationshipCount: int = 0
    labelCount: int = 0
    relationshipTypeCount: int = 0
    propertyKeyCount: int = 0


class PropertyOverview(BaseModel):
    name: str
    types: list[str] = Field(default_factory=list)
    mandatory: bool | None = None


class LabelOverview(BaseModel):
    label: str
    count: int = 0
    properties: list[PropertyOverview] = Field(default_factory=list)


class RelationshipPattern(BaseModel):
    startLabels: list[str] = Field(default_factory=list)
    relationshipType: str
    endLabels: list[str] = Field(default_factory=list)
    count: int = 0
    sampled: bool = False
    sampleLimit: int | None = None


class RelationshipTypeOverview(BaseModel):
    type: str
    count: int = 0
    properties: list[PropertyOverview] = Field(default_factory=list)
    patterns: list[RelationshipPattern] = Field(default_factory=list)


class OverviewGraphNode(BaseModel):
    id: str
    labels: list[str] = Field(default_factory=list)
    caption: str
    properties: dict[str, Any] = Field(default_factory=dict)


class OverviewGraphRelationship(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_: str = Field(alias="from")
    to: str
    type: str
    caption: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class OverviewGraphStats(BaseModel):
    nodeCount: int
    relationshipCount: int
    truncated: bool = False


class OverviewGraph(BaseModel):
    nodes: list[OverviewGraphNode] = Field(default_factory=list)
    relationships: list[OverviewGraphRelationship] = Field(default_factory=list)
    stats: OverviewGraphStats = Field(
        default_factory=lambda: OverviewGraphStats(nodeCount=0, relationshipCount=0)
    )
    warnings: list[str] = Field(default_factory=list)


class GeneratedDashboardCard(BaseModel):
    id: str
    type: str
    title: str
    description: str
    cypher: str | None = None
    dataKey: str | None = None


class DatabaseSchemaResponse(BaseModel):
    connection: DashboardConnection
    stats: DashboardStats
    labels: list[LabelOverview] = Field(default_factory=list)
    relationships: list[RelationshipTypeOverview] = Field(default_factory=list)
    patterns: list[RelationshipPattern] = Field(default_factory=list)
    schemaGraph: OverviewGraph
    sampleGraph: OverviewGraph
    generatedCards: list[GeneratedDashboardCard] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: Literal["apoc", "fallback"] = "fallback"


def _records(result: CypherExecutionResult) -> list[dict[str, Any]]:
    if result.error:
        raise RuntimeError(result.error)
    return result.records


def _try_read(query: str) -> list[dict[str, Any]] | None:
    try:
        return _records(get_cypher_gateway().read_cypher(query))
    except Exception:
        logger.debug("Dashboard introspection query failed: %s", query, exc_info=True)
        return None


def _read_required(query: str) -> list[dict[str, Any]]:
    try:
        return _records(get_cypher_gateway().read_cypher(query))
    except Exception as exc:
        logger.warning("Required dashboard introspection query failed", exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to inspect the connected Neo4j database"
        ) from exc


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _clean_rel_type(value: Any) -> str:
    return str(value or "").strip(":` ")


def _property_from_record(record: dict[str, Any]) -> PropertyOverview | None:
    name = record.get("propertyName")
    if not name:
        return None
    return PropertyOverview(
        name=str(name),
        types=_as_str_list(record.get("propertyTypes")),
        mandatory=record.get("mandatory"),
    )


def _fetch_stats_from_apoc() -> tuple[DashboardStats | None, dict[str, int], dict[str, int]]:
    rows = _try_read("CALL apoc.meta.stats()")
    if not rows:
        return None, {}, {}
    row = rows[0]
    labels = {str(k): _as_int(v) for k, v in (row.get("labels") or {}).items()}
    rel_types = {str(k): _as_int(v) for k, v in (row.get("relTypesCount") or {}).items()}
    return (
        DashboardStats(
            nodeCount=_as_int(row.get("nodeCount")),
            relationshipCount=_as_int(row.get("relCount")),
            labelCount=_as_int(row.get("labelCount")),
            relationshipTypeCount=_as_int(row.get("relTypeCount")),
            propertyKeyCount=_as_int(row.get("propertyKeyCount")),
        ),
        labels,
        rel_types,
    )


def _fetch_label_counts() -> dict[str, int]:
    rows = _read_required("""
        MATCH (n)
        UNWIND labels(n) AS label
        RETURN label, count(*) AS count
        ORDER BY count DESC
    """)
    return {str(row.get("label")): _as_int(row.get("count")) for row in rows}


def _fetch_relationship_counts() -> dict[str, int]:
    rows = _read_required("""
        MATCH ()-[r]->()
        RETURN type(r) AS type, count(*) AS count
        ORDER BY count DESC
    """)
    return {_clean_rel_type(row.get("type")): _as_int(row.get("count")) for row in rows}


def _fetch_node_count() -> int:
    rows = _read_required("MATCH (n) RETURN count(n) AS count")
    return _as_int(rows[0].get("count")) if rows else 0


def _fetch_property_key_count() -> int:
    rows = _try_read(
        "CALL db.propertyKeys() YIELD propertyKey RETURN count(propertyKey) AS count"
    )
    return _as_int(rows[0].get("count")) if rows else 0


def _fetch_node_properties() -> dict[str, list[PropertyOverview]]:
    rows = _try_read("""
        CALL db.schema.nodeTypeProperties()
        YIELD nodeLabels, propertyName, propertyTypes, mandatory
        RETURN nodeLabels, propertyName, propertyTypes, mandatory
        ORDER BY nodeLabels, propertyName
    """) or []
    properties: dict[str, list[PropertyOverview]] = {}
    for row in rows:
        prop = _property_from_record(row)
        if prop is None:
            continue
        for label in _as_str_list(row.get("nodeLabels")):
            properties.setdefault(label, []).append(prop)
    return properties


def _fetch_relationship_properties() -> dict[str, list[PropertyOverview]]:
    rows = _try_read("""
        CALL db.schema.relTypeProperties()
        YIELD relType, propertyName, propertyTypes, mandatory
        RETURN relType, propertyName, propertyTypes, mandatory
        ORDER BY relType, propertyName
    """) or []
    properties: dict[str, list[PropertyOverview]] = {}
    for row in rows:
        prop = _property_from_record(row)
        if prop is None:
            continue
        rel_type = _clean_rel_type(row.get("relType"))
        properties.setdefault(rel_type, []).append(prop)
    return properties


def _fetch_patterns() -> list[RelationshipPattern]:
    rows = _try_read(f"""
        MATCH (a)-[r]->(b)
        WITH a, r, b
        LIMIT {PATTERN_SAMPLE_LIMIT}
        RETURN labels(a) AS startLabels,
               type(r) AS relationshipType,
               labels(b) AS endLabels,
               count(*) AS count
        ORDER BY count DESC
        LIMIT 100
    """) or []
    return [
        RelationshipPattern(
            startLabels=_as_str_list(row.get("startLabels")),
            relationshipType=_clean_rel_type(row.get("relationshipType")),
            endLabels=_as_str_list(row.get("endLabels")),
            count=_as_int(row.get("count")),
            sampled=True,
            sampleLimit=PATTERN_SAMPLE_LIMIT,
        )
        for row in rows
    ]


def _build_schema_graph(
    labels: list[LabelOverview], patterns: list[RelationshipPattern]
) -> OverviewGraph:
    nodes = [
        OverviewGraphNode(
            id=label.label,
            labels=["Label"],
            caption=label.label,
            properties={"count": label.count, "propertyCount": len(label.properties)},
        )
        for label in labels
    ]
    node_ids = {node.id for node in nodes}
    relationships: list[OverviewGraphRelationship] = []
    for index, pattern in enumerate(patterns):
        start = pattern.startLabels[0] if pattern.startLabels else "Unknown"
        end = pattern.endLabels[0] if pattern.endLabels else "Unknown"
        if start not in node_ids or end not in node_ids:
            continue
        relationships.append(
            OverviewGraphRelationship(
                id=f"schema-{index}",
                from_=start,
                to=end,
                type=pattern.relationshipType,
                caption=pattern.relationshipType,
                properties={"count": pattern.count, "sampled": pattern.sampled},
            )
        )
    return OverviewGraph(
        nodes=nodes,
        relationships=relationships,
        stats=OverviewGraphStats(
            nodeCount=len(nodes),
            relationshipCount=len(relationships),
        ),
    )


def _fetch_sample_graph() -> OverviewGraph:
    rows = _try_read("MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50") or []
    if not rows:
        return OverviewGraph()
    graph = records_to_nvl_graph(rows, max_nodes=75, max_relationships=100)
    return OverviewGraph.model_validate(graph)


def _generated_cards(
    labels: list[LabelOverview], relationships: list[RelationshipTypeOverview]
) -> list[GeneratedDashboardCard]:
    cards = [
        GeneratedDashboardCard(
            id="total-nodes",
            type="kpi",
            title="Total Nodes",
            description="Live count of nodes in the connected database.",
            cypher="MATCH (n) RETURN count(n) AS value",
            dataKey="stats.nodeCount",
        ),
        GeneratedDashboardCard(
            id="nodes-by-label",
            type="bar",
            title="Nodes by Label",
            description="Distribution of node labels detected from the database.",
            cypher="MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY count DESC",
            dataKey="labels",
        ),
    ]
    if labels or relationships:
        cards.append(
            GeneratedDashboardCard(
                id="sample-graph",
                type="sampleGraph",
                title="Sample Data Graph",
                description="Actual sampled nodes and relationships from the connected database.",
                cypher="MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 50",
                dataKey="sampleGraph",
            )
        )
    return cards


def build_schema_overview() -> DatabaseSchemaResponse:
    runtime = get_neo4j_runtime_state()
    connection = DashboardConnection(
        connected=bool(runtime.get("connected")),
        uri=str(runtime.get("uri", "")),
        database=str(runtime.get("database", "")),
        source=str(runtime.get("source", "")),
    )
    if not connection.connected:
        return DatabaseSchemaResponse(
            connection=connection,
            stats=DashboardStats(),
            schemaGraph=OverviewGraph(),
            sampleGraph=OverviewGraph(),
            warnings=["Neo4j is not connected. Configure a database before loading the overview."],
        )

    warnings: list[str] = []
    stats, label_counts, relationship_counts = _fetch_stats_from_apoc()
    source: Literal["apoc", "fallback"] = "apoc" if stats else "fallback"
    if stats is None:
        warnings.append("APOC metadata was unavailable; used fallback Cypher introspection.")
        label_counts = _fetch_label_counts()
        relationship_counts = _fetch_relationship_counts()
        stats = DashboardStats(
            nodeCount=_fetch_node_count(),
            relationshipCount=sum(relationship_counts.values()),
            labelCount=len(label_counts),
            relationshipTypeCount=len(relationship_counts),
            propertyKeyCount=_fetch_property_key_count(),
        )

    node_properties = _fetch_node_properties()
    relationship_properties = _fetch_relationship_properties()
    patterns = _fetch_patterns()

    labels = [
        LabelOverview(
            label=label,
            count=count,
            properties=node_properties.get(label, []),
        )
        for label, count in sorted(label_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    pattern_by_type: dict[str, list[RelationshipPattern]] = {}
    for pattern in patterns:
        pattern_by_type.setdefault(pattern.relationshipType, []).append(pattern)
    relationships = [
        RelationshipTypeOverview(
            type=rel_type,
            count=count,
            properties=relationship_properties.get(rel_type, []),
            patterns=pattern_by_type.get(rel_type, []),
        )
        for rel_type, count in sorted(relationship_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    return DatabaseSchemaResponse(
        connection=connection,
        stats=stats,
        labels=labels,
        relationships=relationships,
        patterns=patterns,
        schemaGraph=_build_schema_graph(labels, patterns),
        sampleGraph=_fetch_sample_graph(),
        generatedCards=_generated_cards(labels, relationships),
        warnings=warnings,
        source=source,
    )
