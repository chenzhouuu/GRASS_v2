"""Persistence for backend-owned runs and their event streams.

The in-memory broker stays the fast path for live viewers; these helpers are
the durable record — status history, crash-recoverable replay, and the
startup orphan sweep's raw material.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import delete, func, select, update

from .engine import db_session
from .models import ChatMessage, Run, RunEvent

logger = logging.getLogger(__name__)

TERMINAL_RUN_STATUSES = ("completed", "failed", "stopped")

_EVENT_TTL_MS = 7 * 24 * 3600 * 1000


def _now_ms() -> int:
    return int(datetime.now().timestamp() * 1000)


async def create_run(run_id: str, session_id: str) -> None:
    now = _now_ms()
    async with db_session() as db:
        db.add(
            Run(
                id=run_id,
                session_id=session_id,
                status="running",
                created_at=now,
                updated_at=now,
            )
        )
        await db.commit()


async def set_run_status(
    run_id: str, status: str, *, error: Optional[str] = None
) -> None:
    async with db_session() as db:
        await db.execute(
            update(Run)
            .where(Run.id == run_id)
            .values(status=status, error=error, updated_at=_now_ms())
        )
        await db.commit()


async def get_run(run_id: str) -> Optional[Run]:
    async with db_session() as db:
        return await db.get(Run, run_id)


async def record_run_event(run_id: str, seq: int, event: str, data: str) -> None:
    async with db_session() as db:
        db.add(RunEvent(run_id=run_id, seq=seq, event=event, data=data))
        await db.commit()


async def load_run_events(
    run_id: str, after_seq: int = 0
) -> list[tuple[int, str, str]]:
    """Events after a cursor, in publish order, as (seq, event, data)."""
    async with db_session() as db:
        rows = (
            (
                await db.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                    .order_by(RunEvent.seq.asc())
                )
            )
            .scalars()
            .all()
        )
        return [(r.seq, r.event, r.data) for r in rows]


async def find_orphan_runs() -> list[Run]:
    """Runs the previous process life left non-terminal."""
    async with db_session() as db:
        return list(
            (
                await db.execute(
                    select(Run).where(Run.status.notin_(TERMINAL_RUN_STATUSES))
                )
            )
            .scalars()
            .all()
        )


async def has_assistant_message(run_id: str) -> bool:
    async with db_session() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .where(ChatMessage.run_id == run_id, ChatMessage.role == "assistant")
        )
        return bool(count)


async def delete_expired_run_events() -> int:
    """Drop events of terminal runs older than the 7-day retention window."""
    cutoff = _now_ms() - _EVENT_TTL_MS
    async with db_session() as db:
        result = await db.execute(
            delete(RunEvent).where(
                RunEvent.run_id.in_(
                    select(Run.id).where(
                        Run.status.in_(TERMINAL_RUN_STATUSES),
                        Run.updated_at < cutoff,
                    )
                )
            )
        )
        await db.commit()
        return result.rowcount or 0
