"""Database API endpoints.

Provides direct access to Neo4j for Cypher queries and schema inspection.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..tools.cypher_gateway import (
    get_cypher_gateway,
    reset_cypher_gateway_cache,
    validate_cypher_query,
)
from ..utils.neo4j_connection import (
    apply_runtime_neo4j_config,
    get_neo4j_runtime_state,
)
from ..utils.nvl_transformer import records_to_nvl_graph
from ..utils.schema_loader import fetch_schema_from_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["database"])


# ── Pydantic models ─────────────────────────────────────────────────────────

class CypherRequest(BaseModel):
    query: str
    params: Optional[Dict[str, Any]] = None
    format: Literal["table", "both"] = "both"


class NvlGraphNode(BaseModel):
    id: str
    labels: List[str] = Field(default_factory=list)
    caption: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class NvlGraphRelationship(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_: str = Field(alias="from")
    to: str
    type: Optional[str] = None
    caption: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class NvlGraphStats(BaseModel):
    nodeCount: int
    relationshipCount: int
    truncated: bool = False


class NvlGraphResult(BaseModel):
    nodes: List[NvlGraphNode]
    relationships: List[NvlGraphRelationship]
    stats: NvlGraphStats
    warnings: List[str] = Field(default_factory=list)


class CypherResponse(BaseModel):
    results: List[Dict[str, Any]]
    columns: List[str]
    execution_time_ms: int
    error: Optional[str] = None
    truncated: bool = False
    graph: Optional[NvlGraphResult] = None
    graph_truncated: bool = False
    graph_warnings: List[str] = Field(default_factory=list)
    source: str = "direct"
    validation_warnings: List[str] = Field(default_factory=list)


class CypherValidationRequest(BaseModel):
    query: str


class CypherValidationResponse(BaseModel):
    valid: bool
    read_only: bool
    errors: List[str]
    warnings: List[str]
    requires_approval: bool
    normalized_query: str


class SchemaNode(BaseModel):
    label: str
    properties: List[str]


class SchemaRelationship(BaseModel):
    type: str
    properties: List[str]
    pattern: Optional[str] = None  # e.g., "(State)-[:HAS_COUNTY]->(County)"


class SchemaResponse(BaseModel):
    nodes: List[SchemaNode]
    relationships: List[SchemaRelationship]


class Neo4jConfigRequest(BaseModel):
    uri: str
    username: str
    password: str
    database: str


class Neo4jConfigResponse(BaseModel):
    uri: str
    username: str
    password: str
    database: str
    connected: bool
    source: str


# ── API endpoints ───────────────────────────────────────────────────────────


@router.get("/neo4j/config", response_model=Neo4jConfigResponse)
async def get_runtime_neo4j_config():
    """Return the active Neo4j runtime config and connectivity status."""
    return Neo4jConfigResponse(**get_neo4j_runtime_state())


@router.put("/neo4j/config", response_model=Neo4jConfigResponse)
async def update_runtime_neo4j_config(body: Neo4jConfigRequest):
    """Apply a verified runtime Neo4j config override."""
    try:
        state = apply_runtime_neo4j_config({
            "uri": body.uri,
            "username": body.username,
            "password": body.password,
            "database": body.database,
        })
        reset_cypher_gateway_cache()
    except Exception as e:
        logger.error("Failed to apply Neo4j runtime config: %s", e)
        raise HTTPException(status_code=400, detail=f"Neo4j connection failed: {e}") from e

    return Neo4jConfigResponse(**state)


@router.post("/cypher/validate", response_model=CypherValidationResponse)
async def validate_cypher_endpoint(body: CypherValidationRequest):
    """Validate a Cypher query against GRASS read-only policy without execution."""
    validation = validate_cypher_query(body.query, require_read_only=True)
    return CypherValidationResponse(
        valid=validation.valid,
        read_only=validation.read_only,
        errors=validation.errors,
        warnings=validation.warnings,
        requires_approval=validation.requires_approval,
        normalized_query=validation.normalized_query,
    )


@router.post("/cypher/read", response_model=CypherResponse)
async def execute_read_cypher_query(body: CypherRequest):
    """Execute a validated read-only Cypher query against Neo4j."""
    return await execute_cypher_query(body)

@router.post("/cypher", response_model=CypherResponse)
async def execute_cypher_query(body: CypherRequest):
    """Execute a read-only Cypher query against Neo4j.

    This legacy route is kept for the Database panel, but it now uses the same
    validated gateway as the Cypher agent.
    """
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    result = get_cypher_gateway().read_cypher(body.query, body.params or {})
    if result.error:
        logger.warning("Cypher query failed: %s", result.error)
    else:
        logger.info(
            "Cypher query executed via %s: %d rows in %sms",
            result.source,
            result.row_count,
            result.execution_time_ms,
        )

    graph_payload = None
    graph_truncated = False
    graph_warnings: list[str] = []
    if body.format == "both" and result.error is None:
        graph_payload = records_to_nvl_graph(result.records)
        graph_truncated = bool(graph_payload.get("stats", {}).get("truncated", False))
        graph_warnings = list(graph_payload.get("warnings", []))

    return CypherResponse(
        results=result.records,
        columns=result.columns,
        execution_time_ms=result.execution_time_ms or 0,
        error=result.error,
        truncated=result.truncated,
        graph=graph_payload,
        graph_truncated=graph_truncated,
        graph_warnings=graph_warnings,
        source=result.source,
        validation_warnings=result.validation.warnings if result.validation else [],
    )


@router.get("/schema", response_model=SchemaResponse)
async def get_neo4j_schema():
    """Get the Neo4j database schema.

    Returns node labels, relationship types, and their properties.
    This is used by the Database panel's schema browser.
    """
    try:
        schema = fetch_schema_from_db()

        nodes = [
            SchemaNode(
                label=node.get("label", ""),
                properties=[p.get("name", "") for p in node.get("properties", []) if p.get("name")],
            )
            for node in schema.get("nodes", [])
        ]

        rel_patterns: dict[str, str] = {}
        for p in schema.get("patterns", []):
            rel_type = p.get("type", "")
            if rel_type and rel_type not in rel_patterns:
                rel_patterns[rel_type] = f"(:{p.get('source', '?')})-[:{rel_type}]->(:{p.get('target', '?')})"

        relationships = [
            SchemaRelationship(
                type=rel.get("type", ""),
                properties=[p.get("name", "") for p in rel.get("properties", []) if p.get("name")],
                pattern=rel_patterns.get(rel.get("type", "")),
            )
            for rel in schema.get("relationships", [])
        ]

        logger.info(
            f"Schema retrieved: {len(nodes)} node types, "
            f"{len(relationships)} relationship types"
        )

        return SchemaResponse(nodes=nodes, relationships=relationships)

    except Exception as e:
        logger.error(f"Failed to get schema: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get schema: {str(e)}")
