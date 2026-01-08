"""Cases routes for Legal AI Vault"""
import logging
import os
import time
import json
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.user import User
from app.config import config
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
    - Индексы и ассистенты Yandex больше не используются (мигрировали на pgvector)
    
    Удаление происходит до удаления записи из БД, чтобы иметь доступ к ID.
    """
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Note: Yandex Index and Assistant resources are no longer used (migrated to pgvector)
    # If case has old yandex_index_id or yandex_assistant_id, they are left as-is for historical records
    # PGVector documents are automatically deleted via CASCADE in database schema
    
    try:
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


@router.get("/{case_id}/files")
async def get_case_files(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of files for a case with classifications"""
    from app.models.analysis import DocumentClassification
    
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get all files for the case
    files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
    
    # Get classifications for all files
    file_ids = [file.id for file in files]
    classifications = db.query(DocumentClassification).filter(
        DocumentClassification.file_id.in_(file_ids)
    ).all() if file_ids else []
    
    # Create mapping file_id -> classification
    classification_map = {c.file_id: c for c in classifications if c.file_id}
    
    return {
        "documents": [
            {
                "id": file.id,
                "filename": file.filename,
                "file_type": file.file_type,
                "created_at": file.created_at.isoformat() if file.created_at else None,
                "doc_type": classification.doc_type if (classification := classification_map.get(file.id)) else None,
                "classification": {
                    "doc_type": classification.doc_type,
                    "relevance_score": classification.relevance_score,
                    "is_privileged": classification.is_privileged == "true",
                    "privilege_type": classification.privilege_type,
                    "key_topics": classification.key_topics or [],
                    "confidence": float(classification.confidence) if classification.confidence else 0.0,
                    "reasoning": classification.reasoning,
                    "needs_human_review": classification.needs_human_review == "true"
                } if (classification := classification_map.get(file.id)) else None
            }
            for file in files
        ],
        "total": len(files)
    }


@router.get("/{case_id}/documents/{doc_id}/view")
async def view_document_fragment(
    case_id: str,
    doc_id: str,
    start: Optional[int] = Query(None, description="Start character position"),
    end: Optional[int] = Query(None, description="End character position"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Phase 4: Deep link endpoint for viewing document fragments
    
    Returns document fragment and metadata for citation deep links
    """
    # Verify case ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Find file by doc_id (doc_id is file_id for new documents)
    file = db.query(FileModel).filter(
        FileModel.id == doc_id,
        FileModel.case_id == case_id
    ).first()
    
    if not file:
        raise HTTPException(status_code=404, detail="Документ не найден")
    
    # Get document text
    if not file.original_text:
        raise HTTPException(status_code=404, detail="Содержимое документа недоступно")
    
    text = file.original_text
    
    # Extract fragment if start/end provided
    fragment_text = None
    if start is not None and end is not None:
        try:
            start_pos = max(0, int(start))
            end_pos = min(len(text), int(end))
            if start_pos < end_pos:
                fragment_text = text[start_pos:end_pos]
        except (ValueError, TypeError):
            pass
    
    return {
        "doc_id": doc_id,
        "file_id": file.id,
        "filename": file.filename,
        "fragment": fragment_text if fragment_text else text[:1000],  # Return first 1000 chars if no fragment
        "char_start": start,
        "char_end": end,
        "full_text_length": len(text),
        "file_type": file.file_type,
        "created_at": file.created_at.isoformat() if file.created_at else None
    }


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
    
    # Определяем content type
    content_type = "text/plain"
    if file.file_type == "pdf":
        content_type = "application/pdf"
    elif file.file_type == "docx":
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif file.file_type == "xlsx":
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    
    # Приоритет 1: Читаем файл из БД (новый способ хранения)
    if file.file_content:
        return Response(
            content=file.file_content,
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{file.filename}"'
            }
        )
    
    # Приоритет 2: Fallback на файловую систему (для старых файлов, обратная совместимость)
    if file.file_path:
        import os
        from app.config import config
        
        # Проверяем, является ли file_path абсолютным путем
        if os.path.isabs(file.file_path):
            file_full_path = file.file_path
        else:
            file_full_path = os.path.join(config.UPLOAD_DIR, file.file_path)
        
        
        if os.path.exists(file_full_path):
            try:
                with open(file_full_path, 'rb') as f:
                    file_content = f.read()
                
                
                return Response(
                    content=file_content,
                    media_type=content_type,
                    headers={
                        "Content-Disposition": f'inline; filename="{file.filename}"'
                    }
                )
            except Exception as e:
                logger.error(f"Error reading original file {file_full_path}: {e}")
                # Для PDF файлов не возвращаем текст при ошибке чтения
                if file.file_type == "pdf":
                    logger.error(f"Failed to read PDF file {file_full_path}: {e}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Ошибка при чтении PDF файла: {str(e)}"
                    )
                # Fallback to text if file read fails (для не-PDF файлов)
    
    # Fallback: return text content if original file not available
    
    # Для PDF файлов не возвращаем текст - это вызовет ошибку "Invalid PDF structure"
    # Вместо этого возвращаем ошибку 404 или пустой ответ
    if file.file_type == "pdf":
        logger.warning(f"PDF file {file_id} not found on disk, but file_type is pdf. Cannot return text as PDF.")
        raise HTTPException(
            status_code=404,
            detail=f"Оригинальный PDF файл не найден на сервере. Файл: {file.filename}"
        )
    
    # Для других типов файлов возвращаем текст как fallback
    if not file.original_text:
        raise HTTPException(
            status_code=404,
            detail="Содержимое файла недоступно"
        )
    
    return Response(
        content=file.original_text.encode('utf-8'),
        media_type="text/plain",  # Always return as text/plain for text fallback
        headers={
            "Content-Disposition": f'inline; filename="{file.filename}"'
        }
    )

