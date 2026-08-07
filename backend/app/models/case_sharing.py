"""Case membership and invite models for collaborative case access."""
from __future__ import annotations

from datetime import datetime
import secrets
import uuid

from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from app.models.case import Base

CASE_ROLE_OWNER = "owner"
CASE_ROLE_EDITOR = "editor"
CASE_ROLE_VIEWER = "viewer"

CASE_ROLES = (CASE_ROLE_OWNER, CASE_ROLE_EDITOR, CASE_ROLE_VIEWER)
CASE_INVITE_ROLES = (CASE_ROLE_EDITOR, CASE_ROLE_VIEWER)

ROLE_RANK = {
    CASE_ROLE_VIEWER: 1,
    CASE_ROLE_EDITOR: 2,
    CASE_ROLE_OWNER: 3,
}


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def role_at_least(actual: str, minimum: str) -> bool:
    return ROLE_RANK.get(actual, 0) >= ROLE_RANK.get(minimum, 99)


def new_invite_token() -> str:
    return secrets.token_urlsafe(32)


class CaseMember(Base):
    """Active membership of a user on a case."""

    __tablename__ = "case_members"
    __table_args__ = (
        UniqueConstraint("case_id", "user_id", name="uq_case_members_case_user"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(
        String,
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False, default=CASE_ROLE_EDITOR)
    added_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    case = relationship("Case", backref="members")
    user = relationship("User", foreign_keys=[user_id])
    added_by_user = relationship("User", foreign_keys=[added_by])


class CaseInvite(Base):
    """Pending (or accepted/revoked) invitation to a case by email."""

    __tablename__ = "case_invites"
    __table_args__ = (
        Index("ix_case_invites_case_email", "case_id", "email"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(
        String,
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email = Column(String(255), nullable=False, index=True)
    role = Column(String(20), nullable=False, default=CASE_ROLE_EDITOR)
    token = Column(String(128), nullable=False, unique=True, index=True)
    invited_by = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at = Column(DateTime, nullable=False)
    accepted_at = Column(DateTime, nullable=True)
    accepted_by_user_id = Column(
        String,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    case = relationship("Case", backref="invites")
    invited_by_user = relationship("User", foreign_keys=[invited_by])
    accepted_by_user = relationship("User", foreign_keys=[accepted_by_user_id])

    @property
    def is_pending(self) -> bool:
        if self.accepted_at is not None or self.revoked_at is not None:
            return False
        return self.expires_at > datetime.utcnow()
