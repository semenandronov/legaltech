"""Persistent append-only store for agent run SSE events."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent_run_event import AgentRunEvent


class AgentRunEventStore:
    def __init__(self, db: Session):
        self.db = db

    def append(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> AgentRunEvent:
        next_seq = (
            self.db.query(func.coalesce(func.max(AgentRunEvent.seq), 0))
            .filter(AgentRunEvent.run_id == run_id)
            .scalar()
        )
        seq = int(next_seq or 0) + 1
        row = AgentRunEvent(
            run_id=run_id,
            seq=seq,
            event_type=event_type,
            payload=payload or {},
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def list_since(self, run_id: str, after_seq: int = 0, limit: int = 5000) -> List[AgentRunEvent]:
        return (
            self.db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.seq > after_seq)
            .order_by(AgentRunEvent.seq.asc())
            .limit(limit)
            .all()
        )

    def get_by_seq(self, run_id: str, seq: int) -> Optional[AgentRunEvent]:
        return (
            self.db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.seq == seq)
            .first()
        )

    def max_seq(self, run_id: str) -> int:
        value = (
            self.db.query(func.coalesce(func.max(AgentRunEvent.seq), 0))
            .filter(AgentRunEvent.run_id == run_id)
            .scalar()
        )
        return int(value or 0)
