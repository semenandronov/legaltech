"""Saved workflow scenario for a case (reusable task template)."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON

from app.models.case import Base


class CaseWorkflow(Base):
    __tablename__ = "case_workflows"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    user_task = Column(Text, nullable=False)
    default_file_ids = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "case_id": self.case_id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "user_task": self.user_task,
            "default_file_ids": self.default_file_ids or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
