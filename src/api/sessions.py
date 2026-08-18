"""Session management API endpoints and persistence helpers (Postgres/ORM)."""

import logging
import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from ..db import (
    ChatMessage,
    ChatSession,
    SessionModelConfig,
    SessionPreferences,
    create_tables,
    db_session,
)
from ..utils.model_loader import (
    get_default_session_model_config,
    normalize_session_model_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

_session_runtime_api_keys: dict[str, dict[str, str]] = {}


# ── Pydantic models ─────────────────────────────────────────────────────────

class Message(BaseModel):
    id: int
    role: str  # "user" | "assistant"
    content: str
    timestamp: int  # epoch ms
    metadata: dict | None = None  # visualizations, mapData, agentProgress


class SessionCreate(BaseModel):
    title: Optional[str] = None


class SessionUpdate(BaseModel):
    title: Optional[str] = None
    updatedAt: Optional[int] = None
    messageCount: Optional[int] = None
    lastMessagePreview: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    message_count: int
    last_message_preview: Optional[str] = None


class SessionDetail(BaseModel):
    id: str
    title: str
    created_at: int
    updated_at: int
    message_count: int
    last_message_preview: Optional[str] = None
    messages: List[Message]


class SessionAgentModel(BaseModel):
    provider: str
    model: str


class SessionApiKeys(BaseModel):
    openai: str = ""
    anthropic: str = ""
    google: str = ""


class SessionModelConfigRequest(BaseModel):
    agent_models: dict[str, SessionAgentModel] = Field(default_factory=dict)
    api_keys: SessionApiKeys = Field(default_factory=SessionApiKeys)


class SessionModelConfigResponse(BaseModel):
    session_id: str
    agent_models: dict[str, SessionAgentModel]
    api_keys: SessionApiKeys
    source: str


class SessionPreferencesPayload(BaseModel):
    """Generic per-session preferences blob."""
    query_history: list[dict[str, Any]] = Field(default_factory=list)
    saved_queries: list[dict[str, Any]] = Field(default_factory=list)
    active_right_tab: str = "agent"
    map_viewport: dict[str, Any] = Field(
        default_factory=lambda: {"center": [40.8, -77.9], "zoom": 7}
    )
    layer_visibility: dict[str, bool] = Field(
        default_factory=lambda: {
            "markers": True,
            "clusters": True,
            "routes": True,
            "heatmap": False,
        }
    )


# ── Database initialization ─────────────────────────────────────────────────

async def init_db():
    """Initialize the Postgres session store (create missing tables)."""
    _session_runtime_api_keys.clear()
    await create_tables()
    logger.info("✓ Sessions database initialized")


# ── Helper functions ────────────────────────────────────────────────────────

def generate_title(first_message: str) -> str:
    """Generate a session title from the first user message."""
    # Take first 50 chars, strip, and add ellipsis if truncated
    title = first_message.strip()[:50]
    if len(first_message) > 50:
        title += "..."
    return title or "New Session"


def _session_summary_stmt():
    preview = (
        select(func.substr(ChatMessage.content, 1, 120))
        .where(ChatMessage.session_id == ChatSession.id)
        .order_by(ChatMessage.id.desc())
        .limit(1)
        .correlate(ChatSession)
        .scalar_subquery()
    )
    return (
        select(
            ChatSession.id,
            ChatSession.title,
            ChatSession.created_at,
            ChatSession.updated_at,
            func.count(ChatMessage.id).label("message_count"),
            preview.label("last_message_preview"),
        )
        .outerjoin(ChatMessage, ChatMessage.session_id == ChatSession.id)
        .group_by(ChatSession.id)
    )


async def get_session_summary(session_id: str) -> dict[str, Any] | None:
    """Return a session summary row or None if it does not exist."""
    async with db_session() as db:
        row = (
            await db.execute(
                _session_summary_stmt().where(ChatSession.id == session_id)
            )
        ).one_or_none()
        return dict(row._mapping) if row else None


async def ensure_session_exists(
    session_id: str | None = None,
    *,
    title: str | None = None,
) -> dict[str, Any]:
    """Return an existing session summary, creating the session if needed."""
    if session_id:
        existing = await get_session_summary(session_id)
        if existing is not None:
            return existing

    now = int(datetime.now().timestamp() * 1000)
    session_id = session_id or str(uuid.uuid4())
    session_title = title or "New Session"

    async with db_session() as db:
        db.add(
            ChatSession(
                id=session_id,
                title=session_title,
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()

    logger.info("Created session %s: %s", session_id, session_title)
    summary = await get_session_summary(session_id)
    if summary is None:
        raise RuntimeError(f"Failed to create session {session_id}")
    return summary


async def append_message(
    session_id: str,
    *,
    role: str,
    content: str,
    timestamp: int | None = None,
    run_id: str | None = None,
    metadata: dict | None = None,
) -> dict[str, Any]:
    """Insert a message and refresh the session metadata."""
    message_ts = timestamp or int(datetime.now().timestamp() * 1000)

    async with db_session() as db:
        db.add(
            ChatMessage(
                session_id=session_id,
                run_id=run_id,
                role=role,
                content=content,
                timestamp=message_ts,
                meta=metadata,
            )
        )
        await db.flush()

        session = await db.get(ChatSession, session_id)
        if session is not None:
            if role == "user":
                user_message_count = await db.scalar(
                    select(func.count())
                    .select_from(ChatMessage)
                    .where(
                        ChatMessage.session_id == session_id,
                        ChatMessage.role == "user",
                    )
                )
                if user_message_count == 1 and session.title == "New Session":
                    session.title = generate_title(content)
            session.updated_at = message_ts

        await db.commit()

    summary = await get_session_summary(session_id)
    if summary is None:
        raise RuntimeError(f"Session {session_id} disappeared after appending a message")
    return summary


async def get_session_model_config_payload(session_id: str) -> dict[str, Any]:
    """Return the effective model config for a session."""
    session_summary = await get_session_summary(session_id)
    if session_summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    async with db_session() as db:
        stored = await db.get(SessionModelConfig, session_id)

    source = "defaults"
    if stored is not None and stored.config:
        try:
            config = normalize_session_model_config(stored.config)
            source = "session"
        except Exception as exc:
            logger.warning("Invalid persisted session model config for %s: %s", session_id, exc)
            config = get_default_session_model_config()
            source = "defaults"
    else:
        config = get_default_session_model_config()

    runtime_api_keys = _session_runtime_api_keys.get(session_id, {})
    for provider, value in runtime_api_keys.items():
        config["api_keys"][provider] = value
    if runtime_api_keys:
        source = "session"

    return {
        "session_id": session_id,
        "agent_models": config["agent_models"],
        "api_keys": config["api_keys"],
        "source": source,
    }


async def get_effective_session_model_config(session_id: str) -> dict[str, Any]:
    """Return only the effective agent models + API keys for a session."""
    payload = await get_session_model_config_payload(session_id)
    return {
        "agent_models": payload["agent_models"],
        "api_keys": payload["api_keys"],
    }


def _diff_session_model_config(config: dict[str, Any]) -> dict[str, Any]:
    """Return only the explicit overrides relative to YAML defaults."""
    defaults = get_default_session_model_config()
    agent_overrides = {
        agent: model
        for agent, model in config.get("agent_models", {}).items()
        if defaults["agent_models"].get(agent) != model
    }
    api_key_overrides = {
        provider: value
        for provider, value in config.get("api_keys", {}).items()
        if value  # only persist non-empty keys
    }
    return {
        "agent_models": agent_overrides,
        "api_keys": api_key_overrides,
    }


async def save_session_model_config(
    session_id: str,
    raw_config: dict[str, Any],
) -> dict[str, Any]:
    """Persist a normalized session model config."""
    session_summary = await get_session_summary(session_id)
    if session_summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    config = normalize_session_model_config(raw_config)
    overrides = _diff_session_model_config(config)
    runtime_api_keys = {
        provider: value
        for provider, value in config.get("api_keys", {}).items()
        if value
    }
    if runtime_api_keys:
        _session_runtime_api_keys[session_id] = runtime_api_keys
    else:
        _session_runtime_api_keys.pop(session_id, None)
    now = int(datetime.now().timestamp() * 1000)

    async with db_session() as db:
        if overrides["agent_models"] or overrides.get("api_keys"):
            await db.merge(
                SessionModelConfig(
                    session_id=session_id, config=overrides, updated_at=now
                )
            )
            source = "session"
        else:
            await db.execute(
                delete(SessionModelConfig).where(
                    SessionModelConfig.session_id == session_id
                )
            )
            source = "defaults"
        await db.commit()

    return {
        "session_id": session_id,
        "agent_models": config["agent_models"],
        "api_keys": config["api_keys"],
        "source": source,
    }


async def get_session_preferences(session_id: str) -> dict[str, Any]:
    """Return only the stored preferences for a session."""
    async with db_session() as db:
        stored = await db.get(SessionPreferences, session_id)

    if stored is not None and isinstance(stored.preferences, dict):
        return stored.preferences
    return {}


async def save_session_preferences_data(
    session_id: str, preferences: dict[str, Any]
) -> dict[str, Any]:
    """Persist session preferences."""
    session_summary = await get_session_summary(session_id)
    if session_summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    now = int(datetime.now().timestamp() * 1000)

    async with db_session() as db:
        await db.merge(
            SessionPreferences(
                session_id=session_id, preferences=preferences, updated_at=now
            )
        )
        await db.commit()

    return preferences


# ── API endpoints ───────────────────────────────────────────────────────────

@router.get("", response_model=List[SessionResponse])
async def list_sessions():
    """List all sessions with metadata."""
    async with db_session() as db:
        rows = (
            await db.execute(
                _session_summary_stmt().order_by(ChatSession.updated_at.desc())
            )
        ).all()
        return [dict(row._mapping) for row in rows]


@router.post("", response_model=SessionResponse)
async def create_session(body: SessionCreate):
    """Create a new session."""
    return await ensure_session_exists(title=body.title)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str):
    """Get session details with full message history."""
    session_summary = await get_session_summary(session_id)
    if not session_summary:
        raise HTTPException(status_code=404, detail="Session not found")

    async with db_session() as db:
        message_rows = (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.asc())
            )
        ).scalars().all()

    messages = [
        Message(
            id=m.id,
            role=m.role,
            content=m.content,
            timestamp=m.timestamp,
            metadata=m.meta,
        )
        for m in message_rows
    ]

    return SessionDetail(
        id=session_summary["id"],
        title=session_summary["title"],
        created_at=session_summary["created_at"],
        updated_at=session_summary["updated_at"],
        message_count=session_summary["message_count"],
        last_message_preview=session_summary["last_message_preview"],
        messages=messages,
    )


@router.get("/{session_id}/model-config", response_model=SessionModelConfigResponse)
async def get_session_model_config(session_id: str):
    """Get the effective session-scoped model config."""
    return await get_session_model_config_payload(session_id)


@router.put("/{session_id}/model-config", response_model=SessionModelConfigResponse)
async def update_session_model_config(
    session_id: str,
    body: SessionModelConfigRequest,
):
    """Persist the session-scoped model config override."""
    return await save_session_model_config(session_id, body.model_dump())


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, body: SessionUpdate):
    """Update session metadata (title, timestamps, etc.)."""
    now = body.updatedAt or int(datetime.now().timestamp() * 1000)

    async with db_session() as db:
        session = await db.get(ChatSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        if body.title is not None:
            session.title = body.title
        session.updated_at = now
        await db.commit()

    row = await get_session_summary(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return row


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its messages."""
    async with db_session() as db:
        result = await db.execute(
            delete(ChatSession).where(ChatSession.id == session_id)
        )
        await db.commit()

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Session not found")
    _session_runtime_api_keys.pop(session_id, None)

    logger.info(f"Deleted session {session_id}")
    return {"ok": True}


@router.get("/{session_id}/preferences")
async def get_preferences(session_id: str):
    """Get per-session UI preferences (query history, saved queries, etc.)."""
    session_summary = await get_session_summary(session_id)
    if session_summary is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return await get_session_preferences(session_id)


@router.put("/{session_id}/preferences")
async def update_preferences(session_id: str, body: SessionPreferencesPayload):
    """Persist per-session UI preferences."""
    return await save_session_preferences_data(session_id, body.model_dump())
