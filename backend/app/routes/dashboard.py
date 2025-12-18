"""Dashboard routes for Legal AI Vault"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from datetime import datetime, timedelta
from typing import List, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case
from app.models.user import User
from app.models.analysis import AnalysisResult
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
    created_at: str
    updated_at: str


class CasesListResponse(BaseModel):
    """Response model for cases list"""
    cases: List[CaseListItem]
    total: int
    skip: int
    limit: int


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get user dashboard statistics"""
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    # Total cases
    total_cases = db.query(func.count(Case.id)).filter(
        Case.user_id == current_user.id
    ).scalar() or 0
    
    # Total documents
    total_documents = db.query(func.sum(Case.num_documents)).filter(
        Case.user_id == current_user.id
    ).scalar()
    total_documents = int(total_documents) if total_documents is not None else 0
    
    # Total analyses
    total_analyses = db.query(func.count(AnalysisResult.id)).join(
        Case, AnalysisResult.case_id == Case.id
    ).filter(
        Case.user_id == current_user.id
    ).scalar() or 0
    
    # Cases this month
    cases_this_month = db.query(func.count(Case.id)).filter(
        Case.user_id == current_user.id,
        Case.created_at >= month_start
    ).scalar() or 0
    
    # Documents this month
    documents_this_month = db.query(func.sum(Case.num_documents)).filter(
        Case.user_id == current_user.id,
        Case.created_at >= month_start
    ).scalar()
    documents_this_month = int(documents_this_month) if documents_this_month is not None else 0
    
    # Analyses this month
    analyses_this_month = db.query(func.count(AnalysisResult.id)).join(
        Case, AnalysisResult.case_id == Case.id
    ).filter(
        Case.user_id == current_user.id,
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
    """Get list of user's cases with pagination and filters"""
    query = db.query(Case).filter(Case.user_id == current_user.id)
    
    # Apply filters
    if status:
        query = query.filter(Case.status == status)
    if case_type:
        query = query.filter(Case.case_type == case_type)
    
    # Get total count
    total = query.count()
    
    # Get cases
    cases = query.order_by(desc(Case.updated_at)).offset(skip).limit(limit).all()
    
    return CasesListResponse(
        cases=[
            CaseListItem(
                id=case.id,
                title=case.title or None,
                case_type=case.case_type or None,
                status=case.status or "pending",
                num_documents=case.num_documents or 0,
                created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
                updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat()
            )
            for case in cases
        ],
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
    """Get recent cases"""
    cases = db.query(Case).filter(
        Case.user_id == current_user.id
    ).order_by(desc(Case.updated_at)).limit(limit).all()
    
    return [
        CaseListItem(
            id=case.id,
            title=case.title or None,
            case_type=case.case_type or None,
            status=case.status or "pending",
            num_documents=case.num_documents or 0,
            created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
            updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat()
        )
        for case in cases
    ]

