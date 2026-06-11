"""Publish and subscribe agent run events (DB source of truth + NOTIFY hints)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

from app.config import config
from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.agent_runs.event_channels import run_notify_channel
from app.services.agent_runs.async_event_store import (
    append_event,
    get_run_by_id,
    list_events_since,
)
from app.services.agent_runs.postgres_listener import PostgresNotifyListener, emit_notify
from app.services.agent_runs.schemas import AgentRunEventType, AgentRunStreamEvent
from app.services.agent_runs.terminal_events import build_terminal_event

logger = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = frozenset(
    {
        AgentRunEventType.run_completed.value,
        AgentRunEventType.run_failed.value,
        AgentRunEventType.error.value,
        AgentRunEventType.interrupt.value,
        "run_cancelled",
    }
)


class AgentRunEventBus:
    """Append events to Postgres and fan-out via NOTIFY + polling fallback."""

    @staticmethod
    async def publish(run_id: str, event: AgentRunStreamEvent) -> int:
        payload = event.model_dump(mode="json", exclude_none=True)
        row = await append_event(run_id, event.type.value, payload)
        await emit_notify(run_notify_channel(run_id), {"run_id": run_id, "seq": row.seq})
        return row.seq

    @staticmethod
    def _row_to_sse(row) -> str:
        payload = dict(row.payload or {})
        payload.setdefault("type", row.event_type)
        payload.setdefault("run_id", row.run_id)
        if "timestamp" not in payload:
            created = row.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                payload["timestamp"] = created.isoformat().replace("+00:00", "Z")
        import json

        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @classmethod
    async def subscribe_sse(
        cls,
        run_id: str,
        *,
        after_seq: int = 0,
        poll_interval_sec: float = 0.4,
        timeout_sec: float = 3600.0,
    ) -> AsyncIterator[str]:
        """
        Replay events from DB, then tail new rows (LISTEN hint + polling fallback).
        """
        import time

        channel = run_notify_channel(run_id)
        listener: Optional[PostgresNotifyListener] = None
        notify_event = asyncio.Event()
        tail_task: Optional[asyncio.Task] = None

        try:
            listener = PostgresNotifyListener([channel])
            await asyncio.wait_for(listener.start(), timeout=8.0)

            async def _on_notify(_item: dict) -> None:
                notify_event.set()

            tail_task = asyncio.create_task(cls._drain_notify(listener, _on_notify))
        except Exception as exc:
            logger.warning(
                "LISTEN unavailable for run_id=%s; polling-only mode: %s",
                run_id,
                exc,
            )
            listener = None

        last_seq = after_seq
        started = time.monotonic()
        idle_started = started

        try:
            while True:
                now = time.monotonic()
                if now - started > timeout_sec:
                    logger.info("SSE subscribe timeout run_id=%s", run_id)
                    return

                rows = await list_events_since(run_id, after_seq=last_seq)

                if rows:
                    idle_started = now

                for row in rows:
                    last_seq = row.seq
                    yield cls._row_to_sse(row)
                    if row.event_type in TERMINAL_EVENT_TYPES:
                        return

                idle_limit = float(
                    getattr(config, "AGENT_RUNS_SSE_IDLE_SEC", 600) or 600
                )
                if now - idle_started > idle_limit:
                    run = await get_run_by_id(run_id)
                    if run and run.status not in AgentRunStatus.TERMINAL:
                        idle_started = now
                        continue
                    if run:
                        yield cls._row_to_sse_from_terminal(run)
                    logger.warning("SSE subscribe idle timeout run_id=%s", run_id)
                    return

                if tail_task is not None:
                    try:
                        await asyncio.wait_for(notify_event.wait(), timeout=poll_interval_sec)
                        notify_event.clear()
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(poll_interval_sec)
        finally:
            if tail_task is not None:
                tail_task.cancel()
                try:
                    await tail_task
                except asyncio.CancelledError:
                    pass
            if listener is not None:
                await listener.stop()

    @staticmethod
    async def _drain_notify(listener: PostgresNotifyListener, on_item) -> None:
        async for item in listener.events():
            await on_item(item)

    @classmethod
    def _row_to_sse_from_terminal(cls, run: AgentRun) -> str:
        event = build_terminal_event(run)
        import json

        payload = event.model_dump(mode="json", exclude_none=True)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
