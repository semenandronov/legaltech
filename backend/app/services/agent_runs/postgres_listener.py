"""Dedicated async Postgres LISTEN connection (session mode, not pooler)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional

from app.config import config
from app.utils.postgres_notify_dsn import listen_notify_dsn

logger = logging.getLogger(__name__)


class PostgresNotifyListener:
    """Long-lived LISTEN on one or more channels; yields parsed JSON payloads."""

    def __init__(self, channels: list[str]):
        self._channels = [c for c in channels if c]
        self._conn = None
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self._reader_task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if not self._channels:
            return
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for LISTEN/NOTIFY") from exc

        dsn = listen_notify_dsn(config.DATABASE_URL)
        self._conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
        for channel in self._channels:
            await self._conn.execute(f"LISTEN {channel}")
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info("Postgres LISTEN started on channels=%s", self._channels)

    async def _read_loop(self) -> None:
        assert self._conn is not None
        try:
            async for notify in self._conn.notifies():
                if self._stopped.is_set():
                    break
                payload = self._parse_payload(notify.payload)
                if payload is not None:
                    await self._queue.put(payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Postgres LISTEN loop ended: %s", exc, exc_info=True)

    @staticmethod
    def _parse_payload(raw: Optional[str]) -> Optional[dict]:
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    async def events(self) -> AsyncIterator[dict]:
        while not self._stopped.is_set():
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                yield item
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stopped.set()
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                logger.debug("LISTEN connection close failed", exc_info=True)
            self._conn = None


async def emit_notify(channel: str, payload: dict) -> None:
    """Fire-and-forget NOTIFY with small JSON hint (full payload lives in agent_run_events)."""
    if not channel:
        return
    try:
        import psycopg
    except ImportError:
        logger.debug("psycopg unavailable; skipping NOTIFY on %s", channel)
        return

    dsn = listen_notify_dsn(config.DATABASE_URL)
    body = json.dumps(payload, ensure_ascii=False)
    if len(body) > 7500:
        body = json.dumps({"truncated": True}, ensure_ascii=False)

    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True)
    try:
        await conn.execute("SELECT pg_notify(%s, %s)", (channel, body))
    finally:
        await conn.close()
