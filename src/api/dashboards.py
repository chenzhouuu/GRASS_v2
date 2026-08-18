"""Database-aware dashboard API endpoints."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from ..dashboard.card_executor import execute_dashboard_card
from ..dashboard.catalog import build_catalog_for_runtime
from ..dashboard.context import build_dashboard_context
from ..dashboard.introspection import DatabaseSchemaResponse, build_schema_overview
from ..dashboard.models import (
    DashboardCardExecuteRequest,
    DashboardCardResult,
    DashboardCatalogResponse,
    DashboardContextResponse,
)
from ..tools.cypher_gateway import get_cypher_gateway

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])
logger = logging.getLogger(__name__)
_DASHBOARD_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dashboard-api")


async def run_dashboard_sync(func):
    """Run synchronous dashboard work without relying on Starlette's threadpool wrapper."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_DASHBOARD_EXECUTOR, func)


@router.get("/context", response_model=DashboardContextResponse)
async def get_dashboard_context() -> DashboardContextResponse:
    """Return connection identity and fingerprint for dashboard invalidation."""
    return await run_dashboard_sync(build_dashboard_context)


@router.get("/catalog", response_model=DashboardCatalogResponse)
async def get_dashboard_catalog() -> DashboardCatalogResponse:
    """Return card definitions for the connected database."""
    return await run_dashboard_sync(lambda: build_catalog_for_runtime(force_refresh=True))


@router.post("/cards/execute", response_model=DashboardCardResult)
async def execute_card(request: DashboardCardExecuteRequest) -> DashboardCardResult:
    """Execute a single dashboard card query."""
    catalog = await run_dashboard_sync(build_catalog_for_runtime)
    card = next((item for item in catalog.cards if item.id == request.cardId), None)
    if card is None or not card.cypher:
        raise HTTPException(status_code=404, detail="Unknown dashboard card")
    if catalog.fingerprint != request.fingerprint:
        raise HTTPException(status_code=409, detail="Dashboard context is stale")
    return await run_dashboard_sync(
        lambda: execute_dashboard_card(
            gateway=get_cypher_gateway(),
            card_id=request.cardId,
            cypher=request.cypher,
            expected_cypher=card.cypher,
            timeout_ms=request.timeoutMs,
            max_rows=card.maxRows,
        )
    )


@router.get("/schema", response_model=DatabaseSchemaResponse)
async def get_dashboard_schema() -> DatabaseSchemaResponse:
    """Return data model introspection for the connected database."""
    try:
        return await run_dashboard_sync(build_schema_overview)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to generate dashboard schema", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to generate dashboard schema",
        ) from exc


@router.get("/database-overview", response_model=DatabaseSchemaResponse)
async def get_database_overview() -> DatabaseSchemaResponse:
    """Backward-compatible alias for schema overview."""
    return await get_dashboard_schema()
