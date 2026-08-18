"""Dashboard connection context and fingerprint."""

import hashlib
from datetime import datetime, timezone

from ..utils.neo4j_connection import get_neo4j_runtime_state
from .models import DashboardConnection, DashboardContextResponse


def compute_fingerprint(uri: str, database: str, source: str) -> str:
    raw = f"{uri}|{database}|{source}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_dashboard_context() -> DashboardContextResponse:
    runtime = get_neo4j_runtime_state()
    connection = DashboardConnection(
        connected=bool(runtime.get("connected")),
        uri=str(runtime.get("uri", "")),
        database=str(runtime.get("database", "")),
        source=str(runtime.get("source", "")),
    )
    warnings: list[str] = []
    if not connection.connected:
        warnings.append(
            "Neo4j is not connected. Configure a database before loading the dashboard."
        )
    return DashboardContextResponse(
        connection=connection,
        fingerprint=compute_fingerprint(
            connection.uri, connection.database, connection.source
        ),
        generatedAt=datetime.now(timezone.utc).isoformat(),
        warnings=warnings,
    )
