"""Session management API endpoints and persistence helpers."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, List, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..utils.model_loader import (
    get_default_session_model_config,
    normalize_session_model_config,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])

# Database path
DB_PATH = "data/sessions.db"
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
    """Initialize SQLite database with sessions table."""
    _session_runtime_api_keys.clear()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                run_id TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        cursor = await db.execute("PRAGMA table_info(messages)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "run_id" not in columns:
            await db.execute("ALTER TABLE messages ADD COLUMN run_id TEXT")
        if "metadata" not in columns:
            await db.execute("ALTER TABLE messages ADD COLUMN metadata TEXT")
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id)
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS session_model_configs (
                session_id TEXT PRIMARY KEY,
                config_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS session_preferences (
                session_id TEXT PRIMARY KEY,
                preferences_json TEXT NOT NULL DEFAULT '{}',
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        await db.commit()
    logger.info("✓ Sessions database initialized")


# ── Helper functions ────────────────────────────────────────────────────────

def generate_title(first_message: str) -> str:
    """Generate a session title from the first user message."""
    # Take first 50 chars, strip, and add ellipsis if truncated
    title = first_message.strip()[:50]
    if len(first_message) > 50:
        title += "..."
    return title or "New Session"


def _session_summary_query() -> str:
    return """
        SELECT
            s.id,
            s.title,
            s.created_at,
            s.updated_at,
            COUNT(m.id) as message_count,
            (
                SELECT substr(content, 1, 120)
                FROM messages
                WHERE session_id = s.id
                ORDER BY id DESC
                LIMIT 1
            ) as last_message_preview
        FROM sessions s
        LEFT JOIN messages m ON s.id = m.session_id
    """


async def get_session_summary(session_id: str) -> dict[str, Any] | None:
    """Return a session summary row or None if it does not exist."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _session_summary_query() + """
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (session_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


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

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, session_title, now, now),
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
    metadata_json = json.dumps(metadata, default=str) if metadata else None

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO messages (session_id, run_id, role, content, timestamp, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, run_id, role, content, message_ts, metadata_json),
        )

        if role == "user":
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM messages
                WHERE session_id = ? AND role = 'user'
                """,
                (session_id,),
            )
            user_message_count = (await cursor.fetchone())[0]
            if user_message_count == 1:
                await db.execute(
                    """
                    UPDATE sessions
                    SET title = ?, updated_at = ?
                    WHERE id = ? AND title = 'New Session'
                    """,
                    (generate_title(content), message_ts, session_id),
                )
            else:
                await db.execute(
                    "UPDATE sessions SET updated_at = ? WHERE id = ?",
                    (message_ts, session_id),
                )
        else:
            await db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (message_ts, session_id),
            )

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

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT config_json
            FROM session_model_configs
            WHERE session_id = ?
            """,
            (session_id,),
        )
        row = await cursor.fetchone()

    source = "defaults"
    if row and row[0]:
        try:
            config = normalize_session_model_config(json.loads(row[0]))
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

    async with aiosqlite.connect(DB_PATH) as db:
        if overrides["agent_models"] or overrides.get("api_keys"):
            await db.execute(
                """
                INSERT INTO session_model_configs (session_id, config_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, json.dumps(overrides), now),
            )
            source = "session"
        else:
            await db.execute(
                "DELETE FROM session_model_configs WHERE session_id = ?",
                (session_id,),
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
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT preferences_json FROM session_preferences WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()

    if row and row[0]:
        try:
            stored = json.loads(row[0])
            if isinstance(stored, dict):
                return stored
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


async def save_session_preferences_data(
    session_id: str, preferences: dict[str, Any]
) -> dict[str, Any]:
    """Persist session preferences."""
    session_summary = await get_session_summary(session_id)
    if session_summary is None:
        raise HTTPException(status_code=404, detail="Session not found")

    now = int(datetime.now().timestamp() * 1000)
    prefs_json = json.dumps(preferences, default=str)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO session_preferences (session_id, preferences_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                preferences_json = excluded.preferences_json,
                updated_at = excluded.updated_at
            """,
            (session_id, prefs_json, now),
        )
        await db.commit()

    return preferences


# ── API endpoints ───────────────────────────────────────────────────────────

@router.get("", response_model=List[SessionResponse])
async def list_sessions():
    """List all sessions with metadata."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            _session_summary_query() + """
            GROUP BY s.id
            ORDER BY s.updated_at DESC
            """
        )

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


@router.post("", response_model=SessionResponse)
async def create_session(body: SessionCreate):
    """Create a new session."""
    return await ensure_session_exists(title=body.title)


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(session_id: str):
    """Get session details with full message history."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        session_summary = await get_session_summary(session_id)
        if not session_summary:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get messages
        cursor = await db.execute(
            """
            SELECT id, role, content, timestamp, metadata
            FROM messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        )
        message_rows = await cursor.fetchall()

        messages = []
        for row in message_rows:
            row_dict = dict(row)
            # Parse metadata JSON if present
            raw_meta = row_dict.pop("metadata", None)
            if raw_meta and isinstance(raw_meta, str):
                try:
                    row_dict["metadata"] = json.loads(raw_meta)
                except json.JSONDecodeError:
                    row_dict["metadata"] = None
            else:
                row_dict["metadata"] = None
            messages.append(Message(**row_dict))

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

    async with aiosqlite.connect(DB_PATH) as db:
        # Build SET clause dynamically based on provided fields
        updates = ["updated_at = ?"]
        params: list = [now]

        if body.title is not None:
            updates.append("title = ?")
            params.append(body.title)

        params.append(session_id)

        cursor = await db.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await db.commit()

        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Session not found")

        row = await get_session_summary(session_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return row


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and all its messages."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM sessions WHERE id = ?",
            (session_id,),
        )
        await db.commit()

        if cursor.rowcount == 0:
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
