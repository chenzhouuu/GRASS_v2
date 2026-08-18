# Vendored from: https://github.com/aegra/aegra
# Commit: e72c0f5459bc6deb2df6bdfc08077cdf5ce02281 (2026-08-16)
# Copyright (c) Muhammad Ibrahim (@ibbybuilds) and Aegra contributors
# Licensed under the Apache License, Version 2.0 — see src/api/vendor/NOTICE.
#
# Files copied (upstream paths under libs/aegra-api/src/aegra_api/):
#   utils/sse_utils.py        -> generate_event_id, extract_event_sequence
#   models/enums.py           -> RunCancellationAction (single Literal)
#   core/active_runs.py       -> active_runs, explicit_run_cancellations
#   services/base_broker.py   -> BaseRunBroker, BaseBrokerManager
#   services/broker.py        -> RunBroker, BrokerManager, broker_manager
#
# Local adaptations (kept minimal so the file stays diffable against upstream):
#   - `import structlog` replaced with stdlib `logging` (GRASS has no structlog).
#   - `aegra_api.*` imports replaced by the definitions above, copied verbatim.
#   - `_create_broker_manager` Redis branch stripped: it depends on Aegra's
#     settings module and RedisBrokerManager, neither of which is vendored.
#     The in-memory BrokerManager is the only backend here.
# No other lines were changed.

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Literal

logger = logging.getLogger(__name__)


# --- utils/sse_utils.py ----------------------------------------------------


def generate_event_id(run_id: str, sequence: int) -> str:
    """Generate SSE event ID in the format: {run_id}_event_{sequence}

    Args:
        run_id: The run identifier
        sequence: The event sequence number

    Returns:
        Formatted event ID string
    """
    return f"{run_id}_event_{sequence}"


def extract_event_sequence(event_id: str) -> int:
    """Extract numeric sequence from event_id format: {run_id}_event_{sequence}

    Args:
        event_id: The event ID string

    Returns:
        The sequence number, or 0 if extraction fails
    """
    try:
        return int(event_id.split("_event_")[-1])
    except (ValueError, IndexError):
        return 0


# --- models/enums.py -------------------------------------------------------

RunCancellationAction = Literal["cancel", "interrupt"]


# --- core/active_runs.py ---------------------------------------------------
# Global registry of in-flight asyncio tasks for graph executions.
# Defined in a dependency-free module so that any layer (API routes, broker
# managers, streaming service) can import it without circular dependencies.

active_runs: dict[str, asyncio.Task[None]] = {}

# Explicit API cancellations are marked so worker shutdown remains recoverable.
explicit_run_cancellations: set[str] = set()


# --- services/base_broker.py -----------------------------------------------


class BaseRunBroker(ABC):
    """Abstract base class for a run-specific event broker.

    Handles both live event broadcast and replay storage for SSE reconnection.
    """

    @abstractmethod
    async def put(self, event_id: str, payload: Any, *, resumable: bool = True) -> None:
        """Publish an event to live subscribers and optionally store for replay.

        Args:
            event_id: Unique event identifier (format: {run_id}_event_{seq}).
            payload: The event data (typically a tuple like ("values", {...})).
            resumable: If True, store the event for replay on reconnect.
        """

    @abstractmethod
    def aiter(self) -> AsyncIterator[tuple[str, Any]]:
        """Async iterator yielding (event_id, payload) pairs."""
        ...

    @abstractmethod
    async def replay(self, last_event_id: str | None) -> list[tuple[str, Any]]:
        """Return stored events for replay on reconnect.

        Args:
            last_event_id: If provided, return events after this ID.
                           If None, return all stored events.

        Returns:
            List of (event_id, payload) tuples in order.
        """

    @abstractmethod
    def mark_finished(self) -> None:
        """Mark this broker as finished."""

    @abstractmethod
    def is_finished(self) -> bool:
        """Check if this broker is finished."""


class BaseBrokerManager(ABC):
    """Abstract base class for managing multiple RunBroker instances"""

    @abstractmethod
    def get_or_create_broker(self, run_id: str) -> BaseRunBroker:
        """Get or create a broker for a run"""

    @abstractmethod
    def get_broker(self, run_id: str) -> BaseRunBroker | None:
        """Get an existing broker or None"""

    @abstractmethod
    def cleanup_broker(self, run_id: str) -> None:
        """Clean up a broker for a run"""

    @abstractmethod
    def remove_broker(self, run_id: str) -> None:
        """Remove a broker completely"""

    @abstractmethod
    async def start(self) -> None:
        """Start background tasks (cleanup loop, cancel listener, etc.)"""

    @abstractmethod
    async def stop(self) -> None:
        """Stop background tasks and release resources"""

    @abstractmethod
    async def request_cancel(
        self,
        run_id: str,
        action: RunCancellationAction = "cancel",
        *,
        emit_end_event: bool = True,
    ) -> None:
        """Request cancellation of a run.

        In single-instance mode, cancels the local asyncio task directly.
        In multi-instance mode, broadcasts via Redis pub/sub so the owning
        instance can act on it. ``emit_end_event`` is disabled when the API
        has already reconciled the database and owns terminal signaling.
        """

    @abstractmethod
    async def get_event_sequence(self, run_id: str) -> int:
        """Return the current (highest) event sequence number for a run.

        Used by signal methods (cancel, error) to generate the next event ID
        when they need to inject events into a run's stream.
        """

    async def allocate_event_id(self, run_id: str) -> str:
        """Atomically allocate the next event sequence number and return event_id.

        Default implementation uses get_event_sequence + 1 (not atomic).
        Redis backend overrides with atomic INCR.
        """
        counter = await self.get_event_sequence(run_id) + 1
        return generate_event_id(run_id, counter)


# --- services/broker.py ----------------------------------------------------


class RunBroker(BaseRunBroker):
    """In-memory broker with per-subscriber fan-out + replay buffer.

    Each ``aiter()`` caller gets its own queue fed by ``put`` — so multiple
    concurrent SSE consumers on one run (e.g. the v2 SDK's main event stream and
    its separate lifecycle-watcher) each receive every event, matching the Redis
    pub/sub backend. The replay buffer keeps resumable events for reconnect.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.finished = asyncio.Event()
        self._replay_buffer: list[tuple[str, Any]] = []
        self._subscribers: set[asyncio.Queue[tuple[str, Any]]] = set()
        self._created_at = asyncio.get_running_loop().time()

    async def put(self, event_id: str, payload: Any, *, resumable: bool = True) -> None:
        if self.finished.is_set():
            logger.warning(f"Attempted to put event {event_id} into finished broker for run {self.run_id}")
            return

        if resumable:
            self._replay_buffer.append((event_id, payload))

        for queue in list(self._subscribers):
            queue.put_nowait((event_id, payload))

        # Check if this is an end event
        if isinstance(payload, tuple) and len(payload) >= 1 and payload[0] == "end":
            self.mark_finished()

    async def aiter(self) -> AsyncIterator[tuple[str, Any]]:
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        # Register, then replay the buffer into this iterator: any event put
        # between a caller's separate replay() and this registration is still in
        # the buffer, so nothing is dropped. Callers dedup the overlap by event_id.
        self._subscribers.add(queue)
        backlog = list(self._replay_buffer)
        try:
            for event_id, payload in backlog:
                yield event_id, payload
                if isinstance(payload, tuple) and len(payload) >= 1 and payload[0] == "end":
                    return
            while True:
                try:
                    event_id, payload = await asyncio.wait_for(queue.get(), timeout=0.1)
                except TimeoutError:
                    if self.finished.is_set() and queue.empty():
                        break
                    continue
                yield event_id, payload
                if isinstance(payload, tuple) and len(payload) >= 1 and payload[0] == "end":
                    break
        finally:
            self._subscribers.discard(queue)

    async def replay(self, last_event_id: str | None) -> list[tuple[str, Any]]:
        if not self._replay_buffer:
            return []

        if last_event_id is None:
            return list(self._replay_buffer)

        # Find the index after last_event_id
        for i, (eid, _) in enumerate(self._replay_buffer):
            if eid == last_event_id:
                return list(self._replay_buffer[i + 1 :])

        # last_event_id not found — return all
        return list(self._replay_buffer)

    def mark_finished(self) -> None:
        self.finished.set()
        logger.debug(f"Broker for run {self.run_id} marked as finished")

    def is_finished(self) -> bool:
        return self.finished.is_set()

    def is_empty(self) -> bool:
        return all(queue.empty() for queue in self._subscribers)

    def get_age(self) -> float:
        return asyncio.get_running_loop().time() - self._created_at


class BrokerManager(BaseBrokerManager):
    """Manages multiple RunBroker instances with periodic cleanup."""

    def __init__(self) -> None:
        self._brokers: dict[str, RunBroker] = {}
        self._event_counters: dict[str, int] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    def get_or_create_broker(self, run_id: str) -> RunBroker:
        if run_id not in self._brokers:
            self._brokers[run_id] = RunBroker(run_id)
            logger.debug(f"Created new broker for run {run_id}")
        return self._brokers[run_id]

    def get_broker(self, run_id: str) -> RunBroker | None:
        return self._brokers.get(run_id)

    def cleanup_broker(self, run_id: str) -> None:
        if run_id in self._brokers:
            self._brokers[run_id].mark_finished()
            logger.debug(f"Marked broker for run {run_id} for cleanup")

    def remove_broker(self, run_id: str) -> None:
        if run_id in self._brokers:
            self._brokers[run_id].mark_finished()
            del self._brokers[run_id]
            self._event_counters.pop(run_id, None)
            logger.debug(f"Removed broker for run {run_id}")

    async def start(self) -> None:
        """Start the periodic cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_old_brokers())

    async def stop(self) -> None:
        """Stop the periodic cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

    async def request_cancel(
        self,
        run_id: str,
        action: RunCancellationAction = "cancel",
        *,
        emit_end_event: bool = True,
    ) -> None:
        """Cancel a run locally by cancelling its asyncio task."""
        task = active_runs.get(run_id)
        if task is None or task.done():
            return

        logger.info(f"Executing {action} for run {run_id} (local task)")
        task.cancel()

        broker = self.get_or_create_broker(run_id)
        if emit_end_event and not broker.is_finished():
            event_id = await self.allocate_event_id(run_id)
            await broker.put(event_id, ("end", {"status": "interrupted"}))
            self.cleanup_broker(run_id)

    async def allocate_event_id(self, run_id: str) -> str:
        """Allocate the next event ID using an in-memory counter."""
        seq = self._event_counters.get(run_id, 0) + 1
        self._event_counters[run_id] = seq
        return generate_event_id(run_id, seq)

    async def get_event_sequence(self, run_id: str) -> int:
        """Return the current event sequence from the in-memory counter."""
        return self._event_counters.get(run_id, 0)

    async def _cleanup_old_brokers(self) -> None:
        """Remove finished brokers older than 1 hour every 5 minutes."""
        while True:
            try:
                await asyncio.sleep(300)
                to_remove = [
                    run_id
                    for run_id, broker in self._brokers.items()
                    if broker.is_finished() and broker.is_empty() and broker.get_age() > 3600
                ]
                for run_id in to_remove:
                    self.remove_broker(run_id)
                    logger.info(f"Cleaned up old broker for run {run_id}")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error in broker cleanup task")


def _create_broker_manager() -> BaseBrokerManager:
    """Select broker backend.

    Upstream selects RedisBrokerManager when REDIS_BROKER_ENABLED=true;
    that branch is stripped here (see header) — in-memory only.
    """
    logger.info("Using in-memory broker for SSE streaming")
    return BrokerManager()


# Global broker manager instance
broker_manager: BaseBrokerManager = _create_broker_manager()
