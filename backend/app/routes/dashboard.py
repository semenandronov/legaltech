"""Dashboard routes for Legal AI Vault"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import List, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case
from app.models.tabular_review import TabularReview
from app.models.user import User
from app.models.analysis import AnalysisResult
from app.services.case_sharing_service import accessible_case_ids_subquery
from app.utils.authorization import get_case_role
from pydantic import BaseModel

router = APIRouter()


class StatsResponse(BaseModel):
    """Response model for dashboard statistics"""
    total_cases: int
    total_documents: int
    total_analyses: int
    cases_this_month: int
    documents_this_month: int
    analyses_this_month: int


class CaseListItem(BaseModel):
    """Case list item model"""
    id: str
    title: Optional[str]
    case_type: Optional[str]
    status: str
    num_documents: int
    tabular_reviews_count: int = 0
    created_at: str
    updated_at: str
    my_role: Optional[str] = None
    is_shared: bool = False
    owner_name: Optional[str] = None


class CasesListResponse(BaseModel):
    """Response model for cases list"""
    cases: List[CaseListItem]
    total: int
    skip: int
    limit: int


def _case_list_meta(db: Session, case: Case, user_id: str) -> dict:
    role = get_case_role(db, case.id, user_id) or ("owner" if case.user_id == user_id else None)
    is_shared = str(case.user_id) != str(user_id)
    owner_name = None
    if is_shared and case.user_id:
        owner = db.query(User).filter(User.id == case.user_id).first()
        if owner:
            owner_name = owner.full_name or owner.email
    return {"my_role": role, "is_shared": is_shared, "owner_name": owner_name}


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user dashboard statistics (accessible cases)."""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    accessible = accessible_case_ids_subquery(db, current_user.id)

    total_cases = db.query(func.count(Case.id)).filter(Case.id.in_(accessible)).scalar() or 0

    total_documents = db.query(func.sum(Case.num_documents)).filter(Case.id.in_(accessible)).scalar()
    total_documents = int(total_documents) if total_documents is not None else 0

    total_analyses = db.query(func.count(AnalysisResult.id)).join(
        Case, AnalysisResult.case_id == Case.id
    ).filter(
        Case.id.in_(accessible)
    ).scalar() or 0

    cases_this_month = db.query(func.count(Case.id)).filter(
        Case.id.in_(accessible),
        Case.created_at >= month_start
    ).scalar() or 0

    documents_this_month = db.query(func.sum(Case.num_documents)).filter(
        Case.id.in_(accessible),
        Case.created_at >= month_start
    ).scalar()
    documents_this_month = int(documents_this_month) if documents_this_month is not None else 0

    analyses_this_month = db.query(func.count(AnalysisResult.id)).join(
        Case, AnalysisResult.case_id == Case.id
    ).filter(
        Case.id.in_(accessible),
        AnalysisResult.created_at >= month_start
    ).scalar() or 0

    return StatsResponse(
        total_cases=total_cases,
        total_documents=total_documents,
        total_analyses=total_analyses,
        cases_this_month=cases_this_month,
        documents_this_month=documents_this_month,
        analyses_this_month=analyses_this_month
    )


@router.get("/cases", response_model=CasesListResponse)
async def get_cases_list(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    status: Optional[str] = Query(None),
    case_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of accessible cases (owned + shared) with pagination and filters."""
    query = db.query(Case).filter(Case.id.in_(accessible_case_ids_subquery(db, current_user.id)))

    if status:
        query = query.filter(Case.status == status)
    if case_type:
        query = query.filter(Case.case_type == case_type)

    total = query.count()

    reviews_count_subquery = (
        db.query(
            TabularReview.case_id.label("case_id"),
            func.count(TabularReview.id).label("tabular_reviews_count"),
        )
        .group_by(TabularReview.case_id)
        .subquery()
    )

    cases_with_counts = (
        query.outerjoin(reviews_count_subquery, Case.id == reviews_count_subquery.c.case_id)
        .with_entities(
            Case,
            func.coalesce(reviews_count_subquery.c.tabular_reviews_count, 0).label("tabular_reviews_count"),
        )
        .order_by(desc(Case.updated_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

    items: List[CaseListItem] = []
    for case, tabular_reviews_count in cases_with_counts:
        meta = _case_list_meta(db, case, current_user.id)
        items.append(
            CaseListItem(
                id=case.id,
                title=case.title or None,
                case_type=case.case_type or None,
                status=case.status or "pending",
                num_documents=case.num_documents or 0,
                tabular_reviews_count=int(tabular_reviews_count or 0),
                created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
                updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat(),
                my_role=meta["my_role"],
                is_shared=meta["is_shared"],
                owner_name=meta["owner_name"],
            )
        )

    return CasesListResponse(
        cases=items,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/recent", response_model=List[CaseListItem])
async def get_recent_cases(
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get recent accessible cases"""
    cases = db.query(Case).filter(
        Case.id.in_(accessible_case_ids_subquery(db, current_user.id))
    ).order_by(desc(Case.updated_at)).limit(limit).all()

    items: List[CaseListItem] = []
    for case in cases:
        meta = _case_list_meta(db, case, current_user.id)
        items.append(
            CaseListItem(
                id=case.id,
                title=case.title or None,
                case_type=case.case_type or None,
                status=case.status or "pending",
                num_documents=case.num_documents or 0,
                tabular_reviews_count=0,
                created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
                updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat(),
                my_role=meta["my_role"],
                is_shared=meta["is_shared"],
                owner_name=meta["owner_name"],
            )
        )
    return items
