"""Cases routes for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import List, Optional
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case
from app.models.user import User

router = APIRouter()

VALID_CASE_TYPES = ["litigation", "contracts", "dd", "compliance", "other"]
VALID_STATUSES = ["pending", "processing", "completed", "failed"]


class CaseCreateRequest(BaseModel):
    """Request model for creating a case"""
    title: str = Field(..., min_length=1, max_length=255, description="Case title")
    description: Optional[str] = Field(None, max_length=5000, description="Case description")
    case_type: Optional[str] = Field(None, description="Case type: litigation, contracts, dd, compliance, other")
    analysis_config: Optional[dict] = None
    metadata: Optional[dict] = None
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 0:
            raise ValueError('Title cannot be empty')
        if len(v) > 255:
            raise ValueError('Title must be at most 255 characters')
        return v
    
    @field_validator('description')
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
            if len(v) > 5000:
                raise ValueError('Description must be at most 5000 characters')
        return v
    
    @field_validator('case_type')
    @classmethod
    def validate_case_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_CASE_TYPES:
            raise ValueError(f'Case type must be one of: {", ".join(VALID_CASE_TYPES)}')
        return v


class CaseUpdateRequest(BaseModel):
    """Request model for updating a case"""
    title: Optional[str] = Field(None, max_length=255, description="Case title")
    description: Optional[str] = Field(None, max_length=5000, description="Case description")
    case_type: Optional[str] = Field(None, description="Case type")
    status: Optional[str] = Field(None, description="Case status")
    analysis_config: Optional[dict] = None
    metadata: Optional[dict] = None
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                raise ValueError('Title cannot be empty')
            if len(v) > 255:
                raise ValueError('Title must be at most 255 characters')
        return v
    
    @field_validator('description')
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if len(v) == 0:
                return None
            if len(v) > 5000:
                raise ValueError('Description must be at most 5000 characters')
        return v
    
    @field_validator('case_type')
    @classmethod
    def validate_case_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_CASE_TYPES:
            raise ValueError(f'Case type must be one of: {", ".join(VALID_CASE_TYPES)}')
        return v
    
    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_STATUSES:
            raise ValueError(f'Status must be one of: {", ".join(VALID_STATUSES)}')
        return v


class CaseResponse(BaseModel):
    """Response model for case"""
    id: str
    title: Optional[str]
    description: Optional[str]
    case_type: Optional[str]
    status: str
    num_documents: int
    file_names: List[str]
    created_at: str
    updated_at: str


@router.get("/", response_model=List[CaseResponse])
async def get_cases(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of records to return"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of user's cases"""
    cases = db.query(Case).filter(
        Case.user_id == current_user.id
    ).order_by(Case.created_at.desc()).offset(skip).limit(limit).all()
    
    return [
        CaseResponse(
            id=case.id,
            title=case.title,
            description=case.description,
            case_type=case.case_type,
            status=case.status,
            num_documents=case.num_documents,
            file_names=case.file_names,
            created_at=case.created_at.isoformat(),
            updated_at=case.updated_at.isoformat()
        )
        for case in cases
    ]


@router.get("/{case_id}", response_model=CaseResponse)
async def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get case details"""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    return CaseResponse(
        id=case.id,
        title=case.title,
        description=case.description,
        case_type=case.case_type,
        status=case.status,
        num_documents=case.num_documents,
        file_names=case.file_names,
        created_at=case.created_at.isoformat(),
        updated_at=case.updated_at.isoformat()
    )


@router.post("/", response_model=CaseResponse, status_code=201)
async def create_case(
    request: CaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new case"""
    case = Case(
        user_id=current_user.id,
        title=request.title,
        description=request.description,
        case_type=request.case_type,
        status="pending",
        full_text="",  # Will be filled when files are uploaded
        num_documents=0,
        file_names=[],
        analysis_config=request.analysis_config,
        case_metadata=request.metadata
    )
    
    db.add(case)
    db.commit()
    db.refresh(case)
    
    return CaseResponse(
        id=case.id,
        title=case.title,
        description=case.description,
        case_type=case.case_type,
        status=case.status,
        num_documents=case.num_documents,
        file_names=case.file_names,
        created_at=case.created_at.isoformat(),
        updated_at=case.updated_at.isoformat()
    )


@router.put("/{case_id}", response_model=CaseResponse)
async def update_case(
    case_id: str,
    request: CaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update a case"""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Update fields
    if request.title is not None:
        case.title = request.title
    if request.description is not None:
        case.description = request.description
    if request.case_type is not None:
        case.case_type = request.case_type
    if request.status is not None:
        case.status = request.status
    if request.analysis_config is not None:
        case.analysis_config = request.analysis_config
    if request.metadata is not None:
        case.case_metadata = request.metadata
    
    db.commit()
    db.refresh(case)
    
    return CaseResponse(
        id=case.id,
        title=case.title,
        description=case.description,
        case_type=case.case_type,
        status=case.status,
        num_documents=case.num_documents,
        file_names=case.file_names,
        created_at=case.created_at.isoformat(),
        updated_at=case.updated_at.isoformat()
    )


@router.delete("/{case_id}", status_code=204)
async def delete_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a case"""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    db.delete(case)
    db.commit()
    
    return None

