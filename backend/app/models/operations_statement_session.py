"""Persisted UI session for operations registry (bank statement view)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, UniqueConstraint

from app.models.case import Base


class OperationsStatementSession(Base):
    """Per-user view of a bank statement in the operations registry."""

    __tablename__ = "operations_statement_sessions"
    __table_args__ = (
        UniqueConstraint("user_id", "case_id", "file_id", name="uq_ops_stmt_session"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(String(36), nullable=False, index=True)
    filename = Column(String(512), nullable=True)
    ui_state = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
