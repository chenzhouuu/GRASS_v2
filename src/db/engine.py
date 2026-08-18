"""Async engine and session-factory lifecycle for the GRASS Postgres store.

One process-global engine, created lazily from ``DATABASE_URL`` (``.env``).
Tests rebind it to the ``grass_test`` database via ``init_engine()``.
"""

import json
import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base

load_dotenv()

logger = logging.getLogger(__name__)

_engine: Optional[AsyncEngine] = None
_sessionmaker: Optional[async_sessionmaker[AsyncSession]] = None


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (expected in .env)")
    return url


def psycopg_url() -> str:
    """DATABASE_URL as a plain psycopg conninfo (no SQLAlchemy dialect tag).

    Consumers like AsyncPostgresSaver take psycopg URLs directly.
    """
    return database_url().replace("postgresql+psycopg://", "postgresql://", 1)


def init_engine(url: str | None = None, **engine_kwargs: Any) -> AsyncEngine:
    """(Re)create the global engine and session factory."""
    global _engine, _sessionmaker
    _engine = create_async_engine(
        url or database_url(),
        pool_pre_ping=True,
        # Parity with the old store's json.dumps(..., default=str): message
        # metadata may contain non-JSON-native values (datetimes etc.).
        json_serializer=lambda obj: json.dumps(obj, default=str),
        **engine_kwargs,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def db_session() -> AsyncSession:
    """Open a new AsyncSession; use as ``async with db_session() as db:``."""
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker()


async def create_tables() -> None:
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
