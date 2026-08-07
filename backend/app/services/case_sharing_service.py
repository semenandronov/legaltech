"""Case sharing service — members and ownership transfer (closed product: existing users only)."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_sharing import (
    CASE_INVITE_ROLES,
    CASE_ROLE_EDITOR,
    CASE_ROLE_OWNER,
    CASE_ROLE_VIEWER,
    CaseMember,
    normalize_email,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class CaseSharingError(ValueError):
    """Domain error for sharing operations."""


class CaseSharingService:
    def __init__(self, db: Session):
        self.db = db

    def ensure_owner_member(self, case: Case, *, added_by: Optional[str] = None) -> CaseMember:
        if not case.user_id:
            raise CaseSharingError("Case has no owner")
        existing = (
            self.db.query(CaseMember)
            .filter(CaseMember.case_id == case.id, CaseMember.user_id == case.user_id)
            .first()
        )
        if existing:
            if existing.role != CASE_ROLE_OWNER:
                existing.role = CASE_ROLE_OWNER
                self.db.commit()
                self.db.refresh(existing)
            return existing
        member = CaseMember(
            id=str(uuid.uuid4()),
            case_id=case.id,
            user_id=case.user_id,
            role=CASE_ROLE_OWNER,
            added_by=added_by or case.user_id,
        )
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def get_membership(self, case_id: str, user_id: str) -> Optional[CaseMember]:
        return (
            self.db.query(CaseMember)
            .filter(CaseMember.case_id == str(case_id), CaseMember.user_id == str(user_id))
            .first()
        )

    def list_members(self, case_id: str) -> List[Dict[str, Any]]:
        rows = (
            self.db.query(CaseMember, User)
            .join(User, User.id == CaseMember.user_id)
            .filter(CaseMember.case_id == case_id)
            .order_by(CaseMember.created_at.asc())
            .all()
        )
        out: List[Dict[str, Any]] = []
        for member, user in rows:
            out.append(
                {
                    "user_id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": member.role,
                    "added_by": member.added_by,
                    "created_at": member.created_at.isoformat() if member.created_at else None,
                }
            )
        return out

    def invite(
        self,
        *,
        case: Case,
        email: str,
        role: str,
        invited_by: str,
    ) -> Dict[str, Any]:
        """Add an existing user to the case. Accounts are provisioned by admin — no pending links."""
        email_n = normalize_email(email)
        if not email_n or "@" not in email_n:
            raise CaseSharingError("Некорректный email")
        if role not in CASE_INVITE_ROLES:
            raise CaseSharingError("Роль: editor или viewer")

        existing_user = (
            self.db.query(User).filter(func.lower(User.email) == email_n).first()
        )
        if not existing_user:
            raise CaseSharingError(
                "Пользователь с таким email не найден. "
                "Сначала создайте аккаунт у администратора, затем добавьте в дело."
            )
        if existing_user.id == case.user_id:
            raise CaseSharingError("Этот пользователь уже владелец дела")
        membership = self.get_membership(case.id, existing_user.id)
        if membership:
            raise CaseSharingError("Пользователь уже участник дела")

        member = CaseMember(
            id=str(uuid.uuid4()),
            case_id=case.id,
            user_id=existing_user.id,
            role=role,
            added_by=invited_by,
        )
        self.db.add(member)
        self.db.commit()
        return {
            "status": "added",
            "member": {
                "user_id": existing_user.id,
                "email": existing_user.email,
                "full_name": existing_user.full_name,
                "role": role,
            },
        }

    def update_member_role(
        self,
        *,
        case: Case,
        target_user_id: str,
        new_role: str,
        actor_user_id: str,
    ) -> CaseMember:
        if new_role not in (CASE_ROLE_EDITOR, CASE_ROLE_VIEWER, CASE_ROLE_OWNER):
            raise CaseSharingError("Некорректная роль")
        member = self.get_membership(case.id, target_user_id)
        if not member:
            raise CaseSharingError("Участник не найден")

        if member.role == CASE_ROLE_OWNER and new_role != CASE_ROLE_OWNER:
            owners = (
                self.db.query(CaseMember)
                .filter(CaseMember.case_id == case.id, CaseMember.role == CASE_ROLE_OWNER)
                .count()
            )
            if owners <= 1:
                raise CaseSharingError("Нельзя снять роль единственного владельца")

        if new_role == CASE_ROLE_OWNER:
            raise CaseSharingError("Для назначения владельца используйте передачу владения")

        member.role = new_role
        self.db.commit()
        self.db.refresh(member)
        return member

    def remove_member(self, *, case: Case, target_user_id: str) -> None:
        member = self.get_membership(case.id, target_user_id)
        if not member:
            raise CaseSharingError("Участник не найден")
        if member.role == CASE_ROLE_OWNER:
            owners = (
                self.db.query(CaseMember)
                .filter(CaseMember.case_id == case.id, CaseMember.role == CASE_ROLE_OWNER)
                .count()
            )
            if owners <= 1:
                raise CaseSharingError("Нельзя исключить единственного владельца")
        self.db.delete(member)
        self.db.commit()

    def transfer_ownership(self, *, case: Case, new_owner_id: str, actor_id: str) -> None:
        if actor_id != case.user_id:
            raise CaseSharingError("Только текущий владелец может передать дело")
        new_member = self.get_membership(case.id, new_owner_id)
        if not new_member:
            raise CaseSharingError("Новый владелец должен быть участником дела")
        old = self.get_membership(case.id, case.user_id)
        if old:
            old.role = CASE_ROLE_EDITOR
        new_member.role = CASE_ROLE_OWNER
        case.user_id = new_owner_id
        self.db.commit()


def accessible_case_ids_subquery(db: Session, user_id: str):
    """Case ids the user can access via membership (or legacy owner fallback during rollout)."""
    member_ids = db.query(CaseMember.case_id).filter(CaseMember.user_id == str(user_id))
    owned_ids = db.query(Case.id).filter(Case.user_id == str(user_id))
    return member_ids.union(owned_ids)
