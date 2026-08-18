"""GRASS FastAPI Server

This is the integration layer between the Next.js frontend and the LangGraph backend.
It provides REST endpoints and SSE streaming for real-time agent progress updates.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from .utils.neo4j_connection import (
    close_driver,
    get_neo4j_runtime_state,
    initialize_default_connection,
)
from .api import sessions, database, chat, files, dashboards
from .db import dispose_engine, psycopg_url
from .api.vendor.aegra_broker import active_runs, broker_manager
from .utils.prompt_assembler import PromptAssembler
from .utils.session_graph_registry import SessionGraphRegistry

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global state
app_state = {
    "graph_factory": None,
    "checkpointer": None,
    "neo4j_connected": False,
}

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def open_postgres_checkpointer():
    """Open the LangGraph Postgres checkpointer (checkpoint* tables in the
    shared grass database; ``setup()`` creates them and runs migrations)."""
    pool = AsyncConnectionPool(
        psycopg_url(),
        max_size=10,
        open=False,
        # Required by AsyncPostgresSaver: autocommit for setup/migrations,
        # no prepared statements (it drives connections in pipeline mode).
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    try:
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        yield checkpointer
    finally:
        await pool.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler for startup and shutdown events."""
    logger.info("Starting GRASS server...")

    # Initialize sessions database
    await sessions.init_db()

    # Reconcile runs left non-terminal by the previous process life and
    # drop run events past their retention window.
    await chat.startup_run_recovery()

    # Initialize Neo4j connection from env defaults. Do not crash startup if the
    # default config is unavailable; the frontend can apply a runtime override.
    app_state["neo4j_connected"] = initialize_default_connection()
    if app_state["neo4j_connected"]:
        logger.info("Neo4j connection initialized")
    else:
        logger.warning("Neo4j unavailable at startup; waiting for runtime config override")

    async with open_postgres_checkpointer() as checkpointer:
        app_state["checkpointer"] = checkpointer

        try:
            graph_registry = SessionGraphRegistry(
                checkpointer=checkpointer,
                session_config_loader=sessions.get_effective_session_model_config,
                prompt_assembler=PromptAssembler(),
            )
            app_state["graph_factory"] = graph_registry
            chat.set_graph(None)
            chat.set_graph_factory(graph_registry.get_graph)

            logger.info(
                "Session-aware LangGraph registry ready (postgres checkpoints)"
            )
        except Exception as e:
            logger.error(f"Failed to initialize graph registry: {e}")
            raise

        # Broker retention: finished run brokers are swept by this task
        # (1 hour after terminal status, upstream default).
        await broker_manager.start()

        logger.info("GRASS server ready")

        yield

        # Drain in-flight runs BEFORE the checkpointer closes under them —
        # a run outliving its storage writes "closed connection" errors
        # into session history as the assistant reply. Cancellation takes
        # each run through its persist-partial path while storage is open.
        if active_runs:
            logger.info("Cancelling %d in-flight run(s)...", len(active_runs))
            for task in list(active_runs.values()):
                task.cancel()
            await asyncio.gather(
                *list(active_runs.values()), return_exceptions=True
            )

    # Shutdown
    logger.info("Shutting down GRASS server...")
    await broker_manager.stop()
    app_state["checkpointer"] = None
    app_state["graph_factory"] = None
    close_driver()
    logger.info("Neo4j connection closed")
    await dispose_engine()


# Create FastAPI app
app = FastAPI(
    title="GRASS API",
    description="Graph Retrieval-based Agentic Supply Chain System",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware - allow frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Health check endpoint ---------------------------------------------------

@app.get("/api/health")
async def health_check():
    """Health check endpoint to verify server is running."""
    neo4j_status = (
        "connected"
        if get_neo4j_runtime_state().get("connected")
        else "disconnected"
    )
    graph_status = "ready" if app_state.get("graph_factory") else "not_ready"

    return JSONResponse(
        content={
            "status": "healthy",
            "neo4j": neo4j_status,
            "graph": graph_status,
        }
    )


@app.get("/api/files/{file_id}")
async def serve_file(file_id: str):
    """Serve generated files (charts, maps, PDFs) from the data directory."""
    file_path = DATA_DIR / file_id

    if not file_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": f"File not found: {file_id}"}
        )

    # Determine media type based on extension
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".html": "text/html",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".csv": "text/csv",
    }

    media_type = media_types.get(file_path.suffix.lower(), "application/octet-stream")

    return FileResponse(
        path=file_path,
        media_type=media_type,
        filename=file_id,
    )


# -- API routes ---------------------------------------------------------------

# Register routers
app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(database.router)
app.include_router(files.router)
app.include_router(dashboards.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["src", "config"],
        reload_excludes=["data/*", "*.pyc", "__pycache__"],
        log_level="info",
    )
