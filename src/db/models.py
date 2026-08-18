"""SQLAlchemy ORM models for the GRASS Postgres store.

Timestamps are epoch milliseconds (BigInteger) throughout — the frontend
consumes them as-is. JSON payloads use JSONB so they are stored and returned
as Python dicts without manual (de)serialization.
"""

from typing import Any, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ChatSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class ChatMessage(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_session", "session_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Attribute is ``meta`` because ``metadata`` is reserved by Declarative.
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSONB)


class Run(Base):
    """Durable record of a backend-owned run (chat.py drives the lifecycle).

    status: running | awaiting_plan | completed | failed | stopped.
    A non-terminal status with no live task means the backend died mid-run;
    the startup sweep marks those ``failed``.
    """

    __tablename__ = "runs"
    __table_args__ = (Index("idx_runs_session", "session_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class RunEvent(Base):
    """Write-through copy of every SSE frame a run published.

    ``data`` keeps the frame's already-serialized JSON string verbatim so a
    replay reproduces exactly what a live viewer saw.
    """

    __tablename__ = "run_events"

    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SessionModelConfig(Base):
    __tablename__ = "session_model_configs"

    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    config: Mapped[dict[str, Any]] = mapped_column("config_json", JSONB, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)


class SessionPreferences(Base):
    __tablename__ = "session_preferences"

    session_id: Mapped[str] = mapped_column(
        Text, ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    preferences: Mapped[dict[str, Any]] = mapped_column(
        "preferences_json", JSONB, nullable=False, default=dict
    )
    updated_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
