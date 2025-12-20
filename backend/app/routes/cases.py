"""Cases routes for Legal AI Vault"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.user import User
from fastapi.responses import Response, StreamingResponse

logger = logging.getLogger(__name__)
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
            title=case.title or None,
            description=case.description or None,
            case_type=case.case_type or None,
            status=case.status or "pending",
            num_documents=case.num_documents or 0,
            file_names=case.file_names or [],
            created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
            updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat()
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
        title=case.title or None,
        description=case.description or None,
        case_type=case.case_type or None,
        status=case.status or "pending",
        num_documents=case.num_documents or 0,
        file_names=case.file_names or [],
        created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
        updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat()
    )


@router.post("/", response_model=CaseResponse, status_code=201)
async def create_case(
    request: CaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new case"""
    try:
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
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при создании дела: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при создании дела. Попробуйте позже.")
    
    return CaseResponse(
        id=case.id,
        title=case.title or None,
        description=case.description or None,
        case_type=case.case_type or None,
        status=case.status or "pending",
        num_documents=case.num_documents or 0,
        file_names=case.file_names or [],
        created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
        updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat()
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
    
    try:
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
    except Exception as e:
        db.rollback()
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Ошибка при обновлении дела {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при обновлении дела. Попробуйте позже.")
    
    return CaseResponse(
        id=case.id,
        title=case.title or None,
        description=case.description or None,
        case_type=case.case_type or None,
        status=case.status or "pending",
        num_documents=case.num_documents or 0,
        file_names=case.file_names or [],
        created_at=case.created_at.isoformat() if case.created_at else datetime.utcnow().isoformat(),
        updated_at=case.updated_at.isoformat() if case.updated_at else datetime.utcnow().isoformat()
    )


@router.delete("/{case_id}", status_code=204)
async def delete_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a case
    
    ВАЖНО: При удалении кейса также удаляются:
    - Индекс в Yandex AI Studio (yandex_index_id)
    - Ассистент в Yandex AI Studio (yandex_assistant_id)
    
    Удаление происходит до удаления записи из БД, чтобы иметь доступ к ID.
    """
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Сохраняем ID для удаления из Yandex перед удалением из БД
    yandex_index_id = case.yandex_index_id
    yandex_assistant_id = case.yandex_assistant_id
    
    try:
        # Удаляем индекс из Yandex AI Studio (если существует)
        if yandex_index_id:
            try:
                from app.services.yandex_index import YandexIndexService
                index_service = YandexIndexService()
                if index_service.is_available():
                    logger.info(f"Deleting Yandex index {yandex_index_id} for case {case_id}")
                    index_service.delete_index(yandex_index_id)
                    logger.info(f"✅ Deleted Yandex index {yandex_index_id} for case {case_id}")
            except Exception as e:
                # Логируем ошибку, но не блокируем удаление кейса
                logger.warning(f"Failed to delete Yandex index {yandex_index_id} for case {case_id}: {e}", exc_info=True)
        
        # Удаляем ассистента из Yandex AI Studio (если существует)
        if yandex_assistant_id:
            try:
                from app.services.yandex_assistant import YandexAssistantService
                assistant_service = YandexAssistantService()
                if assistant_service.is_available():
                    logger.info(f"Deleting Yandex assistant {yandex_assistant_id} for case {case_id}")
                    assistant_service.delete_assistant(yandex_assistant_id)
                    logger.info(f"✅ Deleted Yandex assistant {yandex_assistant_id} for case {case_id}")
            except Exception as e:
                # Логируем ошибку, но не блокируем удаление кейса
                logger.warning(f"Failed to delete Yandex assistant {yandex_assistant_id} for case {case_id}: {e}", exc_info=True)
        
        # Удаляем кейс из БД
        # CASCADE удалит связанные записи (files, document_chunks, chat_messages и т.д.)
        db.delete(case)
        db.commit()
        
        logger.info(f"✅ Deleted case {case_id} and associated Yandex resources")
        
    except HTTPException:
        # Пробрасываем HTTPException как есть
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Ошибка при удалении дела {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при удалении дела. Попробуйте позже.")
    
    return None


@router.get("/{case_id}/files/{file_id}/content")
async def get_file_content(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get file content (PDF, DOCX, TXT, etc.)"""
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get file
    file = db.query(FileModel).filter(
        FileModel.id == file_id,
        FileModel.case_id == case_id
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="Файл не найден")
    
    # For now, return text content as plain text
    # TODO: In future, store original files and return them for PDF/DOCX
    # For PDF files, we would need to reconstruct PDF from text or store original
    # For now, return text content with appropriate content type
    
    content_type = "text/plain"
    if file.file_type == "pdf":
        content_type = "application/pdf"
        # Note: Currently we only have text, not original PDF
        # This will need to be enhanced to store original files
    elif file.file_type == "docx":
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file.file_type == "xlsx":
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    # Return text content
    # In future, if original files are stored, return the original file
    return Response(
        content=file.original_text.encode('utf-8'),
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{file.filename}"'
        }
    )

