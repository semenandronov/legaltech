"""Agent run ledger for Deep Agents orchestration."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Integer

from app.models.case import Base


class AgentRunStatus:
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    TERMINAL = frozenset({COMPLETED, FAILED, CANCELLED})


class AgentRun(Base):
    """Persistent record of a single deep-agent task execution."""

    __tablename__ = "agent_runs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    thread_id = Column(String(36), nullable=False, unique=True, index=True)
    user_task = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default=AgentRunStatus.PENDING, index=True)
    input_config = Column(JSON, nullable=True)
    selected_file_ids = Column(JSON, nullable=True)
    artifacts = Column(JSON, nullable=True)
    todos = Column(JSON, nullable=True)
    result_summary = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    langfuse_trace_id = Column(String(64), nullable=True)
    total_tool_calls = Column(Integer, nullable=False, default=0)
    worker_instance_id = Column(String(128), nullable=True, index=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "user_task": self.user_task,
            "status": self.status,
            "input_config": self.input_config,
            "selected_file_ids": self.selected_file_ids,
            "artifacts": self.artifacts,
            "todos": self.todos,
            "result_summary": self.result_summary,
            "error_message": self.error_message,
            "langfuse_trace_id": self.langfuse_trace_id,
            "total_tool_calls": int(self.total_tool_calls or 0),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
