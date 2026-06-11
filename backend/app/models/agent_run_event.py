"""Append-only event log for agent run SSE bus."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Integer, BigInteger, UniqueConstraint

from app.models.case import Base


class AgentRunEvent(Base):
    __tablename__ = "agent_run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_agent_run_events_run_seq"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
