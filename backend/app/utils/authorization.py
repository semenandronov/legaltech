"""Centralized object-level authorization checks.

Keep these checks at route boundaries so service methods cannot accidentally
expose data when they are called with user-controlled identifiers.

Case access is membership-based (case_members). Case.user_id remains the
canonical owner for billing/deletion, but route access always goes through
require_case_access / require_case_write / require_case_manage.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.case_sharing import (
    CASE_ROLE_EDITOR,
    CASE_ROLE_OWNER,
    CASE_ROLE_VIEWER,
    CaseMember,
    role_at_least,
)
from app.models.tabular_review import TabularReview


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


def get_case_membership(db: Session, case_id: str, user_id: str) -> Optional[CaseMember]:
    """Return membership row if the user is a member of the case."""
    return (
        db.query(CaseMember)
        .filter(
            CaseMember.case_id == str(case_id),
            CaseMember.user_id == str(user_id),
        )
        .first()
    )


def _legacy_owner_membership(case: Case, user_id: str) -> Optional[CaseMember]:
    """Treat Case.user_id as owner when membership row is missing (pre-backfill)."""
    if case.user_id and str(case.user_id) == str(user_id):
        return CaseMember(
            id="legacy-owner",
            case_id=case.id,
            user_id=str(user_id),
            role=CASE_ROLE_OWNER,
        )
    return None


def get_case_role(db: Session, case_id: str, user_id: str) -> Optional[str]:
    membership = get_case_membership(db, case_id, user_id)
    if membership:
        return membership.role
    case = db.query(Case).filter(Case.id == str(case_id)).first()
    if case is None:
        return None
    legacy = _legacy_owner_membership(case, user_id)
    return legacy.role if legacy else None


def require_case_access(
    db: Session,
    case_id: str,
    user_id: str,
    *,
    min_role: str = CASE_ROLE_VIEWER,
) -> Case:
    """Return case if user has at least min_role membership (404 if no access)."""
    case = db.query(Case).filter(Case.id == str(case_id)).first()
    if case is None:
        raise _not_found()

    membership = get_case_membership(db, case_id, user_id)
    if membership is None:
        membership = _legacy_owner_membership(case, user_id)
    if membership is None:
        raise _not_found()
    if not role_at_least(membership.role, min_role):
        # Member exists but role too low → 403 (not 404) so UI can show readonly reason.
        raise _forbidden()
    return case


def require_case_write(db: Session, case_id: str, user_id: str) -> Case:
    return require_case_access(db, case_id, user_id, min_role=CASE_ROLE_EDITOR)


def require_case_manage(db: Session, case_id: str, user_id: str) -> Case:
    return require_case_access(db, case_id, user_id, min_role=CASE_ROLE_OWNER)


def require_review_access(
    db: Session,
    review_id: str,
    user_id: str,
    *,
    min_role: str = CASE_ROLE_VIEWER,
) -> TabularReview:
    """Load review and authorize via its case membership."""
    review = db.query(TabularReview).filter(TabularReview.id == str(review_id)).first()
    if review is None:
        raise _not_found()
    if not review.case_id:
        # Orphan review: fall back to review.user_id ownership.
        if str(review.user_id) != str(user_id):
            raise _not_found()
        return review
    require_case_access(db, review.case_id, user_id, min_role=min_role)
    return review


def require_review_write(db: Session, review_id: str, user_id: str) -> TabularReview:
    return require_review_access(db, review_id, user_id, min_role=CASE_ROLE_EDITOR)


def require_owned_case(db: Session, case_id: str, user_id: str) -> Case:
    """Compatibility alias: any member with viewer+ access (was owner-only)."""
    return require_case_access(db, case_id, user_id, min_role=CASE_ROLE_VIEWER)


def require_owned_review(db: Session, review_id: str, user_id: str) -> TabularReview:
    """Compatibility alias: review access via case membership (viewer+)."""
    return require_review_access(db, review_id, user_id, min_role=CASE_ROLE_VIEWER)
