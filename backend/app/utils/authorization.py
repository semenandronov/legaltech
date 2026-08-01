"""Centralized object-level authorization checks.

Keep these checks at route boundaries so service methods cannot accidentally
expose data when they are called with user-controlled identifiers.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.tabular_review import TabularReview


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Resource not found",
    )


def require_owned_case(db: Session, case_id: str, user_id: str) -> Case:
    """Return a case only when it belongs to the authenticated user."""
    case = (
        db.query(Case)
        .filter(
            Case.id == str(case_id),
            Case.user_id == str(user_id),
        )
        .first()
    )
    if case is None:
        raise _not_found()
    return case


def require_owned_review(db: Session, review_id: str, user_id: str) -> TabularReview:
    """Return a tabular review only when it belongs to the authenticated user."""
    review = (
        db.query(TabularReview)
        .filter(
            TabularReview.id == str(review_id),
            TabularReview.user_id == str(user_id),
        )
        .first()
    )
    if review is None:
        raise _not_found()
    return review
