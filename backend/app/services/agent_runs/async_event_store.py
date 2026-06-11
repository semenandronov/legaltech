"""Async persistence for agent run SSE events (subscribe/publish hot path)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func, select

from app.models.agent_run import AgentRun
from app.models.agent_run_event import AgentRunEvent
from app.utils.async_database import async_session_scope


async def append_event(run_id: str, event_type: str, payload: Dict[str, Any]) -> AgentRunEvent:
    async with async_session_scope() as session:
        result = await session.execute(
            select(func.coalesce(func.max(AgentRunEvent.seq), 0)).where(
                AgentRunEvent.run_id == run_id
            )
        )
        next_seq = int(result.scalar_one() or 0) + 1
        row = AgentRunEvent(
            run_id=run_id,
            seq=next_seq,
            event_type=event_type,
            payload=payload or {},
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return row


async def list_events_since(
    run_id: str,
    after_seq: int = 0,
    limit: int = 5000,
) -> List[AgentRunEvent]:
    async with async_session_scope() as session:
        result = await session.execute(
            select(AgentRunEvent)
            .where(AgentRunEvent.run_id == run_id, AgentRunEvent.seq > after_seq)
            .order_by(AgentRunEvent.seq.asc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def max_event_seq(run_id: str) -> int:
    async with async_session_scope() as session:
        result = await session.execute(
            select(func.coalesce(func.max(AgentRunEvent.seq), 0)).where(
                AgentRunEvent.run_id == run_id
            )
        )
        return int(result.scalar_one() or 0)


async def get_run_for_user(run_id: str, user_id: str) -> Optional[AgentRun]:
    async with async_session_scope() as session:
        result = await session.execute(
            select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
        )
        return result.scalar_one_or_none()


async def get_run_by_id(run_id: str) -> Optional[AgentRun]:
    async with async_session_scope() as session:
        result = await session.execute(select(AgentRun).where(AgentRun.id == run_id))
        return result.scalar_one_or_none()
