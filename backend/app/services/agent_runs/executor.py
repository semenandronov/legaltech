"""SSE facade: replay/tail agent_run_events (execution runs in worker)."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from app.services.agent_runs.event_bus import AgentRunEventBus
from app.services.agent_runs.route_db import get_stream_run_gate, prepare_stream_resume, terminal_if_no_events
from app.services.agent_runs.schemas import (
    AgentRunEventType,
    AgentRunStreamEvent,
    ResumeAgentRunRequest,
)
from app.services.agent_runs.worker import get_agent_run_worker
from app.utils.sync_db_pool import run_sync_db

logger = logging.getLogger(__name__)


class AgentRunExecutor:
    """Subscribes to the distributed event bus; does not execute LangGraph directly."""

    async def stream_resume(
        self,
        run_id: str,
        user_id: str,
        resume: ResumeAgentRunRequest,
    ) -> AsyncIterator[str]:
        status, payload = await run_sync_db(prepare_stream_resume, run_id, user_id, resume)
        if status == "not_found":
            yield self._error_event(run_id, "run_not_found").to_sse()
            return
        if status == "terminal" and payload:
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return
        if status == "not_waiting":
            yield AgentRunStreamEvent(
                type=AgentRunEventType.error,
                run_id=run_id,
                message="run_not_waiting_for_user",
                data=payload or {},
            ).to_sse()
            return
        if status == "schedule_failed":
            yield self._error_event(run_id, "resume_schedule_failed").to_sse()
            return

        async for chunk in self._subscribe(run_id, user_id):
            yield chunk

    async def stream(self, run_id: str, user_id: str) -> AsyncIterator[str]:
        status, payload = await run_sync_db(get_stream_run_gate, run_id, user_id)
        if status == "not_found":
            yield self._error_event(run_id, "run_not_found").to_sse()
            return
        if status in ("terminal", "waiting") and payload:
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            return

        async for chunk in self._subscribe(run_id, user_id):
            yield chunk

    async def _subscribe(self, run_id: str, user_id: str) -> AsyncIterator[str]:
        yield AgentRunStreamEvent(
            type=AgentRunEventType.stream_open,
            run_id=run_id,
            message="stream connected",
        ).to_sse()

        _ = get_agent_run_worker()

        async for chunk in AgentRunEventBus.subscribe_sse(run_id, after_seq=0):
            yield chunk

        terminal = await run_sync_db(terminal_if_no_events, run_id, user_id)
        if terminal:
            yield f"data: {json.dumps(terminal, ensure_ascii=False)}\n\n"

    @staticmethod
    def _error_event(run_id: str, message: str) -> AgentRunStreamEvent:
        return AgentRunStreamEvent(
            type=AgentRunEventType.error,
            run_id=run_id,
            message=message,
        )
