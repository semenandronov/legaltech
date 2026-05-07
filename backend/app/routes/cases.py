"""Cases routes for Legal AI Vault"""
import asyncio
import logging
import os
import importlib.util
from fastapi import APIRouter, HTTPException, Depends, Query, UploadFile, File
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only
from sqlalchemy.exc import OperationalError
from typing import List, Optional
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.user import User
from app.config import config
from fastapi.responses import Response, StreamingResponse, JSONResponse
from app.services.langchain_loaders import DocumentLoaderService
from app.services.document_classifier_service import DocumentClassifierService
from app.services.document_processor import DocumentProcessor, get_document_processor
from app.services.chat.entity_index_service import merge_case_entity_index
from fastapi import BackgroundTasks
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter()


def _reconnect_db(db: Session) -> None:
    """
    Ensure the DB session has a live connection after a long operation (OCR, etc.).
    pool_pre_ping only fires on pool checkout; a session that already holds a connection
    may have it killed by PostgreSQL SSL keepalive timeout (~60-120s).

    Strategy: ping with SELECT 1. If it fails, invalidate the underlying DBAPI connection
    and rollback the session — SQLAlchemy will check out a fresh connection (with
    pool_pre_ping) on the next ORM call. We must NOT call db.close() because that makes
    the session itself unusable for further operations.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("DB connection lost after long OCR operation — invalidating and reconnecting.")
        # Invalidate tells SQLAlchemy the DBAPI connection is dead without talking to it
        try:
            db.connection().invalidate()
        except Exception:
            pass
        # Rollback clears session transaction state and releases the dead connection
        try:
            db.rollback()
        except Exception:
            pass
        # pool_pre_ping=True ensures the next checkout from pool gets a live connection
        logger.info("DB session reset — will get fresh connection on next operation.")

VALID_CASE_TYPES = ["litigation", "contracts", "dd", "compliance", "other"]
VALID_STATUSES = ["pending", "processing", "completed", "failed"]


def sanitize_text(text: str) -> str:
    """
    Очищает текст от NUL символов и других недопустимых символов для PostgreSQL
    
    Args:
        text: Исходный текст
        
    Returns:
        Очищенный текст без NUL символов
    """
    if not text:
        return text
    
    # Удаляем NUL символы (0x00), которые не поддерживаются PostgreSQL
    # Также заменяем другие недопустимые управляющие символы
    sanitized = text.replace('\x00', '')
    
    # Удаляем другие недопустимые управляющие символы (кроме \n, \r, \t)
    sanitized = ''.join(char for char in sanitized if ord(char) >= 32 or char in '\n\r\t')
    
    return sanitized


def _cleanup_uploaded_files(file_paths: List[str]) -> None:
    """
    Удаляет сохранённые файлы с диска при откате транзакции
    
    Args:
        file_paths: Список путей к файлам для удаления
    """
    for file_path in file_paths:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup file {file_path}: {e}", exc_info=True)
    
    # Также удаляем пустые директории case_id если они остались
    if file_paths:
        try:
            case_upload_dir = os.path.dirname(file_paths[0])
            if os.path.exists(case_upload_dir) and not os.listdir(case_upload_dir):
                os.rmdir(case_upload_dir)
                logger.info(f"Removed empty case directory: {case_upload_dir}")
        except Exception as e:
            logger.warning(f"Failed to remove case directory: {e}", exc_info=True)


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
    case = db.query(Case).options(
        load_only(
            Case.id,
            Case.user_id,
            Case.title,
            Case.description,
            Case.case_type,
            Case.status,
            Case.num_documents,
            Case.file_names,
            Case.created_at,
            Case.updated_at,
        )
    ).filter(
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


@router.get("/{case_id}/suggestions")
async def get_suggestions(
    case_id: str,
    context: Optional[str] = Query(None, description="Текущий контекст для персонализации подсказок"),
    limit: int = Query(5, ge=1, le=20, description="Максимальное количество подсказок"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Получить умные подсказки для дела"""
    # Проверяем доступ к делу
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        from app.services.suggestions_service import SuggestionsService
        from app.services.rag_service import RAGService
        
        # Инициализируем сервисы
        rag_service = RAGService()
        suggestions_service = SuggestionsService(rag_service=rag_service)
        
        # Получаем подсказки
        suggestions = suggestions_service.get_suggestions(
            case_id=case_id,
            context=context,
            limit=limit,
            db=db
        )
        
        # Возвращаем список подсказок
        return [s.dict() for s in suggestions]
    except Exception as e:
        logger.error(f"Error getting suggestions for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при получении подсказок: {str(e)}")


@router.get("/{case_id}/workflow-templates")
async def get_workflow_templates(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Получить список доступных workflow templates для дела"""
    # Проверяем доступ к делу
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    try:
        from app.services.langchain_agents.legacy_stubs import list_workflow_templates
        
        templates = list_workflow_templates()
        return [template.dict() for template in templates]
    except Exception as e:
        logger.error(f"Error getting workflow templates for case {case_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при получении шаблонов: {str(e)}")


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
        # Вручную удаляем зависимые записи (на случай если CASCADE не применился в миграции)
        from sqlalchemy import text
        dependent_tables = [
            "document_versions", "editor_documents",
            "tabular_reviews", "agent_interactions", "agent_interaction_steps",
            "workflow_executions", "folder_items", "folders",
            "playbook_validations",
            "analysis_results", "discrepancies", "timeline_events",
            "document_chunks", "document_classifications",
            "extracted_entities", "privilege_checks", "risks", "analysis_plans",
            "chat_messages",
        ]
        for table_name in dependent_tables:
            try:
                db.execute(text(f"SAVEPOINT sp_{table_name}"))
                db.execute(text(f'DELETE FROM {table_name} WHERE case_id = :cid'), {"cid": case_id})
                db.execute(text(f"RELEASE SAVEPOINT sp_{table_name}"))
            except Exception:
                db.execute(text(f"ROLLBACK TO SAVEPOINT sp_{table_name}"))

        # Также удаляем файлы с диска
        for f in case.files:
            if f.file_path:
                import os
                try:
                    os.remove(f.file_path)
                except OSError:
                    pass

        db.delete(case)
        db.commit()

        logger.info(f"Deleted case {case_id} and all associated data")

    except HTTPException:
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
    case = db.query(Case).options(load_only(Case.id, Case.user_id)).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    from app.models.analysis import DocumentChunk
    from sqlalchemy import func

    # Get all files for the case without loading heavy blob/text payloads
    files = db.query(
        FileModel.id,
        FileModel.filename,
        FileModel.file_type,
        FileModel.folder_id,
        FileModel.created_at,
        func.octet_length(FileModel.file_content).label("file_size"),
        func.length(FileModel.original_text).label("text_length"),
    ).filter(FileModel.case_id == case_id).all()

    # Get classifications for all files
    file_ids = [file.id for file in files]
    classifications = db.query(DocumentClassification).filter(
        DocumentClassification.file_id.in_(file_ids)
    ).all() if file_ids else []

    # Create mapping file_id -> classification
    classification_map = {c.file_id: c for c in classifications if c.file_id}

    # Get max page number per file (as page count approximation)
    page_counts = db.query(
        DocumentChunk.file_id,
        func.max(DocumentChunk.source_page).label("page_count")
    ).filter(
        DocumentChunk.file_id.in_(file_ids)
    ).group_by(DocumentChunk.file_id).all() if file_ids else []
    page_count_map = {row.file_id: row.page_count for row in page_counts if row.page_count is not None}

    return {
        "documents": [
            {
                "id": file.id,
                "filename": file.filename,
                "file_type": file.file_type,
                "folder_id": file.folder_id,
                "created_at": file.created_at.isoformat() if file.created_at else None,
                "size": int(file.file_size) if file.file_size is not None else (int(file.text_length) if file.text_length is not None else None),
                "page_count": page_count_map.get(file.id),
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


@router.get("/{case_id}/files/{file_id}/indexed-chunks")
async def get_file_indexed_chunks(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Все чанки файла из PGVector (как после Docling + индексации) + citation payload для превью в UI.
    """
    case = db.query(Case).options(load_only(Case.id, Case.user_id)).filter(
        Case.id == case_id,
        Case.user_id == current_user.id,
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    file_row = (
        db.query(FileModel)
        .filter(FileModel.id == file_id, FileModel.case_id == case_id)
        .first()
    )
    if not file_row:
        raise HTTPException(status_code=404, detail="Файл не найден")

    processor = get_document_processor()
    docs = processor.vector_store.list_chunks_by_file(case_id, file_id)
    if not docs:
        return {
            "file": {
                "id": file_row.id,
                "filename": file_row.filename,
                "file_type": file_row.file_type,
                "processing_status": file_row.processing_status,
            },
            "chunks": [],
            "total": 0,
        }

    from app.services.chat.citation_payload import (
        build_retrieval_citations,
        fetch_original_text_map_for_case,
    )

    originals = fetch_original_text_map_for_case(db, case_id)
    citations = build_retrieval_citations(
        docs,
        original_text_by_file_id=originals or None,
    )
    chunks_out = []
    for idx, (doc, cit) in enumerate(zip(docs, citations)):
        chunks_out.append(
            {
                "chunk_index": doc.metadata.get("chunk_index", idx),
                "chunk_id": doc.metadata.get("chunk_id"),
                "text_preview": (doc.page_content or "")[:400],
                "citation": cit,
            }
        )

    return {
        "file": {
            "id": file_row.id,
            "filename": file_row.filename,
            "file_type": file_row.file_type,
            "processing_status": file_row.processing_status,
        },
        "chunks": chunks_out,
        "total": len(chunks_out),
    }


class MoveFileRequest(BaseModel):
    folder_id: Optional[str] = None


class UpdateCaseFileTextRequest(BaseModel):
    """Replace stored plain text for a case file (e.g. workflow document_draft .txt)."""
    text: str = Field(..., description="UTF-8 plain text body")


@router.patch("/{case_id}/files/{file_id}")
async def move_file_to_folder(
    case_id: str,
    file_id: str,
    request: MoveFileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Move a file to a folder (or to root if folder_id is null)"""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    file = db.query(FileModel).filter(
        FileModel.id == file_id,
        FileModel.case_id == case_id
    ).first()
    if not file:
        raise HTTPException(status_code=404, detail="Файл не найден")

    # Update file_count on old folder
    if file.folder_id:
        from app.models.folder import Folder
        old_folder = db.query(Folder).filter(Folder.id == file.folder_id).first()
        if old_folder and old_folder.file_count > 0:
            old_folder.file_count -= 1

    file.folder_id = request.folder_id

    # Update file_count on new folder
    if request.folder_id:
        from app.models.folder import Folder
        new_folder = db.query(Folder).filter(Folder.id == request.folder_id).first()
        if new_folder:
            new_folder.file_count += 1

    db.commit()
    return {"id": file.id, "folder_id": file.folder_id}


@router.post("/{case_id}/files")
async def add_files_to_case(
    case_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Add files to an existing case.

    Files are saved immediately (bytes only) and returned at once.
    OCR, classification, and PGVector indexing run in the background.
    Poll GET /{case_id}/processing-status to track progress.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Не загружено ни одного файла")

    # Verify case exists and user has access
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()

    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    allowed_extensions = [ext.replace(".", "") for ext in config.ALLOWED_EXTENSIONS]
    saved_file_paths: List[str] = []
    new_file_ids: List[str] = []

    upload_dir = config.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    case_upload_dir = os.path.join(upload_dir, case_id)
    os.makedirs(case_upload_dir, exist_ok=True)

    try:
        # Strict mode: PDF ingest requires Docling runtime.
        has_pdf = any(
            (f.filename and "." in f.filename and f.filename.rsplit(".", 1)[-1].lower() == "pdf")
            for f in files
        )
        if has_pdf and importlib.util.find_spec("docling") is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Загрузка PDF временно недоступна: не установлен пакет 'docling'. "
                    "Установите зависимости (`pip install -r requirements.txt`) и перезапустите backend."
                ),
            )

        for file in files:
            if not file.filename:
                raise HTTPException(status_code=400, detail="Пустое имя файла недопустимо")

            filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
            _, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
            if ext.lower() not in allowed_extensions:
                raise HTTPException(
                    status_code=400,
                    detail=f"Файл '{filename}' имеет неподдерживаемый формат. Поддерживаются: {', '.join(allowed_extensions)}"
                )

            content = await file.read()

            if len(content) == 0:
                raise HTTPException(status_code=400, detail=f"Файл '{filename}' пуст")

            if len(content) > config.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"Файл '{filename}' слишком большой. Максимум: {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ"
                )

            # Save file to disk
            file_path = os.path.join(case_upload_dir, filename)
            with open(file_path, "wb") as f:
                f.write(content)
            saved_file_paths.append(file_path)

            relative_file_path = os.path.join(case_id, filename)
            file_type = ext.lower()[:50]
            filename = filename[:255]

            file_model = FileModel(
                case_id=case_id,
                filename=filename,
                file_type=file_type,
                original_text="",          # filled by background task
                file_path=relative_file_path,
                file_content=content,
                processing_status="pending",
            )
            try:
                with db.begin_nested():
                    db.add(file_model)
                    _reconnect_db(db)
                    db.flush()
            except OperationalError as op_err:
                logger.warning(
                    "OperationalError on files flush (case_id=%s, filename=%s): %s. Retrying once with fresh connection.",
                    case_id,
                    filename,
                    op_err,
                )
                _reconnect_db(db)
                with db.begin_nested():
                    db.add(file_model)
                    db.flush()
            new_file_ids.append(file_model.id)
            logger.info(f"Queued file {file_model.id} ({filename}) for background processing")

        if not new_file_ids:
            db.rollback()
            _cleanup_uploaded_files(saved_file_paths)
            raise HTTPException(status_code=400, detail="Не удалось сохранить ни одного файла")

        # Update case file list
        existing_files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
        case.num_documents = len(existing_files) + len(new_file_ids) - len(
            [f for f in existing_files if f.id in new_file_ids]
        )
        case.file_names = [f.filename for f in existing_files if f.id not in new_file_ids] + [
            fm.filename for fid in new_file_ids
            for fm in [next((f for f in existing_files if f.id == fid), None)]
            if fm
        ]
        # simpler: just refresh after flush
        db.commit()

        # Re-read for accurate counts
        all_files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
        case.num_documents = len(all_files)
        case.file_names = [f.filename for f in all_files]
        db.commit()

        # Launch background processing task
        import asyncio as _asyncio
        from app.services.file_processor_bg import process_files_background

        async def _bg() -> None:
            try:
                await _asyncio.to_thread(process_files_background, new_file_ids, case_id)
            except Exception as _e:
                logger.error(f"Background processing task error for case {case_id}: {_e}", exc_info=True)

        _asyncio.create_task(_bg())
        logger.info(f"Background processing started for {len(new_file_ids)} files in case {case_id}")

        new_file_objs = db.query(FileModel).filter(FileModel.id.in_(new_file_ids)).all()
        return {
            "files": [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "file_type": f.file_type,
                    "processing_status": f.processing_status,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in new_file_objs
            ],
            "total": len(all_files),
            "added": len(new_file_ids),
            "new_file_ids": new_file_ids,
            "status": "processing",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        _cleanup_uploaded_files(saved_file_paths)
        logger.error(f"Error adding files to case {case_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при добавлении файлов к делу: {str(e)}"
        )


@router.get("/{case_id}/processing-status")
async def get_processing_status(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Return per-file processing status for a case."""
    case = db.query(Case).options(load_only(Case.id, Case.user_id)).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    files = db.query(
        FileModel.id,
        FileModel.filename,
        FileModel.processing_status,
        FileModel.processing_error,
        FileModel.processing_started_at,
    ).filter(FileModel.case_id == case_id).all()
    file_statuses = [
        {
            "id": f.id,
            "filename": f.filename,
            "status": f.processing_status or "ready",
            "error": f.processing_error,
            "processing_started_at": f.processing_started_at.isoformat() if f.processing_started_at else None,
        }
        for f in files
    ]

    all_done = all(s["status"] in ("ready", "error", "cancelled") for s in file_statuses)
    any_processing = any(s["status"] in ("pending", "processing") for s in file_statuses)

    return {
        "case_id": case_id,
        "files": file_statuses,
        "all_done": all_done,
        "any_processing": any_processing,
        "has_errors": any(s["status"] == "error" for s in file_statuses),
    }


@router.post("/{case_id}/files/{file_id}/cancel")
async def cancel_file_processing(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cancel processing of a pending or processing file."""
    case = db.query(Case).filter(Case.id == case_id, Case.user_id == current_user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    file = db.query(FileModel).filter(FileModel.id == file_id, FileModel.case_id == case_id).first()
    if not file:
        raise HTTPException(status_code=404, detail="Файл не найден")
    if file.processing_status not in ("pending", "processing"):
        raise HTTPException(status_code=400, detail="Файл не находится в обработке")
    file.processing_status = "cancelled"
    file.processing_error = "Обработка отменена пользователем"
    db.commit()
    logger.info(f"File {file_id} ({file.filename}) cancelled by user {current_user.id}")
    return {"status": "cancelled"}


@router.delete("/{case_id}/files/{file_id}")
async def delete_file_from_case(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a file from a case
    
    Removes file from database, disk, and updates case metadata.
    Only works for files that haven't been processed yet (not in PGVector).
    """
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
    
    try:
        # Delete file from disk if it exists
        if file.file_path:
            import os
            from app.config import config
            
            if os.path.isabs(file.file_path):
                file_full_path = file.file_path
            else:
                file_full_path = os.path.join(config.UPLOAD_DIR, file.file_path)
            
            if os.path.exists(file_full_path):
                try:
                    os.remove(file_full_path)
                    logger.info(f"Deleted file from disk: {file_full_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete file from disk {file_full_path}: {e}")
        
        # Delete classification if exists
        from app.models.analysis import DocumentClassification
        classifications = db.query(DocumentClassification).filter(
            DocumentClassification.file_id == file_id
        ).all()
        for classification in classifications:
            db.delete(classification)
        
        # Delete file from database (CASCADE will handle related records)
        db.delete(file)
        
        # Update case metadata
        remaining_files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
        case.num_documents = len(remaining_files)
        case.file_names = [f.filename for f in remaining_files]
        
        db.commit()
        logger.info(f"Successfully deleted file {file_id} from case {case_id}")
        
        # Return updated file list
        updated_files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
        
        return {
            "files": [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "file_type": f.file_type,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in updated_files
            ],
            "total": len(updated_files)
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting file {file_id} from case {case_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при удалении файла: {str(e)}"
        )


@router.post("/{case_id}/reindex")
async def reindex_case_files(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reindex all files for a case in PGVector
    
    This will reindex all files that are not yet in the vector store.
    Useful for files that were added before automatic indexing was implemented.
    """
    # Verify case exists and user has access
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get all files for the case
    files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
    
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Нет файлов для переиндексации."
        )
    
    try:
        logger.info(f"Reindexing {len(files)} files for case {case_id}")
        
        document_processor = get_document_processor()
        all_documents = []
        
        # Get classifications for files
        from app.models.analysis import DocumentClassification
        file_ids = [f.id for f in files]
        classifications = db.query(DocumentClassification).filter(
            DocumentClassification.file_id.in_(file_ids)
        ).all() if file_ids else []
        classification_map = {c.file_id: c for c in classifications if c.file_id}
        
        indexed_count = 0
        for file in files:
            if not file.original_text:
                continue
            
            # Build metadata
            metadata = {
                "source": file.filename,
                "file_id": file.id,
                "file_type": file.file_type or "unknown",
            }
            
            # Add classification metadata if available
            classification = classification_map.get(file.id)
            if classification:
                metadata["doc_type"] = classification.doc_type or "other"
                metadata["is_privileged"] = str(classification.is_privileged) if classification.is_privileged else "false"
                metadata["relevance_score"] = classification.relevance_score or 0
            
            # Split text into chunks
            file_documents = document_processor.split_documents(
                text=file.original_text,
                filename=file.filename,
                metadata=metadata,
            )
            merge_case_entity_index(
                case,
                file_id=file.id,
                filename=file.filename,
                text=file.original_text,
            )
            all_documents.extend(file_documents)
            indexed_count += 1
        
        if all_documents:
            logger.info(f"Storing {len(all_documents)} document chunks in PGVector for case {case_id}")
            
            collection_name = document_processor.store_in_vector_db(
                case_id=case_id,
                documents=all_documents,
                db=db,
                original_files=None
            )
            document_processor.prewarm_bm25_index(
                case_id=case_id,
                documents=all_documents,
                force_rebuild=True,
            )
            
            logger.info(f"Successfully reindexed {len(all_documents)} document chunks for case {case_id}")
        
        # Update case full_text
        text_parts = []
        for file in files:
            if file.original_text:
                text_parts.append(f"[{file.filename}]\n{file.original_text}")
        
        if text_parts:
            full_text = "\n\n".join(text_parts)
            MAX_TEXT_LENGTH = 100 * 1024 * 1024
            sanitized_full_text = sanitize_text(full_text)
            if len(sanitized_full_text) > MAX_TEXT_LENGTH:
                sanitized_full_text = sanitized_full_text[:MAX_TEXT_LENGTH]
            case.full_text = sanitized_full_text
            db.commit()
        
        return {
            "status": "success",
            "message": f"Переиндексировано {indexed_count} файлов ({len(all_documents)} чанков)",
            "case_id": case_id,
            "files_indexed": indexed_count,
            "chunks_created": len(all_documents)
        }
        
    except Exception as e:
        logger.error(f"Error reindexing case {case_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при переиндексации: {str(e)}"
        )


@router.post("/reindex-all")
async def reindex_all_cases(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reindex all files for all cases belonging to the current user.
    
    This will reindex all files that are not yet in the vector store.
    """
    # Get all cases for the current user
    cases = db.query(Case).filter(Case.user_id == current_user.id).all()
    
    if not cases:
        return {
            "status": "success",
            "message": "Нет дел для переиндексации",
            "cases_processed": 0,
            "total_files": 0,
            "total_chunks": 0
        }
    
    logger.info(f"Reindexing all files for {len(cases)} cases (user: {current_user.id})")
    
    document_processor = get_document_processor()
    total_files = 0
    total_chunks = 0
    cases_processed = 0
    errors = []
    
    for case in cases:
        try:
            # Get all files for the case
            files = db.query(FileModel).filter(FileModel.case_id == case.id).all()
            
            if not files:
                continue
            
            all_documents = []
            
            # Get classifications for files
            from app.models.analysis import DocumentClassification
            file_ids = [f.id for f in files]
            classifications = db.query(DocumentClassification).filter(
                DocumentClassification.file_id.in_(file_ids)
            ).all() if file_ids else []
            classification_map = {c.file_id: c for c in classifications if c.file_id}
            
            for file in files:
                if not file.original_text:
                    continue
                
                # Build metadata
                metadata = {
                    "source": file.filename,
                    "file_id": file.id,
                    "file_type": file.file_type or "unknown",
                }
                
                # Add classification metadata if available
                classification = classification_map.get(file.id)
                if classification:
                    metadata["doc_type"] = classification.doc_type or "other"
                    metadata["is_privileged"] = str(classification.is_privileged) if classification.is_privileged else "false"
                    metadata["relevance_score"] = classification.relevance_score or 0
                
                # Split text into chunks
                file_documents = document_processor.split_documents(
                    text=file.original_text,
                    filename=file.filename,
                    metadata=metadata,
                )
                merge_case_entity_index(
                    case,
                    file_id=file.id,
                    filename=file.filename,
                    text=file.original_text,
                )
                all_documents.extend(file_documents)
                total_files += 1
            
            if all_documents:
                document_processor.store_in_vector_db(
                    case_id=case.id,
                    documents=all_documents,
                    db=db,
                    original_files=None
                )
                document_processor.prewarm_bm25_index(
                    case_id=case.id,
                    documents=all_documents,
                    force_rebuild=True,
                )
                total_chunks += len(all_documents)
                
                # Update case full_text
                text_parts = []
                for file in files:
                    if file.original_text:
                        text_parts.append(f"[{file.filename}]\n{file.original_text}")
                
                if text_parts:
                    full_text = "\n\n".join(text_parts)
                    MAX_TEXT_LENGTH = 100 * 1024 * 1024
                    sanitized_full_text = sanitize_text(full_text)
                    if len(sanitized_full_text) > MAX_TEXT_LENGTH:
                        sanitized_full_text = sanitized_full_text[:MAX_TEXT_LENGTH]
                    case.full_text = sanitized_full_text
                    db.commit()
            
            cases_processed += 1
            logger.info(f"Reindexed case {case.id}: {len(files)} files, {len(all_documents)} chunks")
            
        except Exception as e:
            logger.error(f"Error reindexing case {case.id}: {e}", exc_info=True)
            errors.append({"case_id": case.id, "error": str(e)})
    
    return {
        "status": "success" if not errors else "partial",
        "message": f"Переиндексировано {cases_processed} дел, {total_files} файлов, {total_chunks} чанков",
        "cases_processed": cases_processed,
        "total_files": total_files,
        "total_chunks": total_chunks,
        "errors": errors if errors else None
    }


@router.post("/{case_id}/process")
async def process_case_files(
    case_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Process all files for a case
    
    Combines all file texts into case.full_text and indexes files in PGVector.
    This should be called after all files have been added to the case.
    Processing runs asynchronously in the background.
    """
    # Verify case exists and user has access
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get all files for the case
    files = db.query(FileModel).filter(FileModel.case_id == case_id).all()
    
    if not files:
        raise HTTPException(
            status_code=400,
            detail="Нет файлов для обработки. Добавьте файлы к делу перед обработкой."
        )
    
    # Update case status to processing
    case.status = "processing"
    db.commit()
    
    # Process files asynchronously
    def process_files_task():
        from app.utils.database import SessionLocal
        process_db = SessionLocal()
        try:
            # Re-fetch case and files in new session
            process_case = process_db.query(Case).filter(Case.id == case_id).first()
            process_files = process_db.query(FileModel).filter(FileModel.case_id == case_id).all()
            
            if not process_case or not process_files:
                logger.error(f"Case {case_id} or files not found during processing")
                return
            
            # Combine all file texts
            text_parts = []
            file_names = []
            
            for file in process_files:
                if file.original_text:
                    text_parts.append(f"[{file.filename}]\n{file.original_text}")
                    file_names.append(file.filename)
            
            if not text_parts:
                logger.error(f"No text content found in files for case {case_id}")
                process_case.status = "failed"
                process_db.commit()
                return
            
            full_text = "\n\n".join(text_parts)
            sanitized_full_text = sanitize_text(full_text)
            
            # Check text length
            MAX_TEXT_LENGTH = 100 * 1024 * 1024  # 100 MB
            if len(sanitized_full_text) > MAX_TEXT_LENGTH:
                logger.warning(f"Full text is very large: {len(sanitized_full_text)} bytes, truncating to {MAX_TEXT_LENGTH}")
                sanitized_full_text = sanitized_full_text[:MAX_TEXT_LENGTH]
            
            # Update case full_text
            process_case.full_text = sanitized_full_text
            process_case.file_names = file_names
            process_db.commit()
            
            # Process files in PGVector
            logger.info(
                f"Preparing documents for PGVector storage for case {case_id}",
                extra={"case_id": case_id, "num_files": len(process_files)}
            )
            
            document_processor = get_document_processor()
            all_documents = []
            
            # Get classifications for files
            from app.models.analysis import DocumentClassification
            file_ids = [f.id for f in process_files]
            classifications = process_db.query(DocumentClassification).filter(
                DocumentClassification.file_id.in_(file_ids)
            ).all() if file_ids else []
            classification_map = {c.file_id: c for c in classifications if c.file_id}
            
            for file in process_files:
                if not file.original_text:
                    continue
                
                # Prepare metadata with classification
                metadata = {
                    "case_id": case_id,
                }
                
                classification = classification_map.get(file.id)
                if classification:
                    metadata["doc_type"] = classification.doc_type
                    metadata["classification_confidence"] = float(classification.confidence) if classification.confidence else 0.0
                    metadata["is_privileged"] = classification.is_privileged == "true"
                    metadata["key_topics"] = classification.key_topics or []
                    metadata["relevance_score"] = classification.relevance_score or 0
                
                # Split text into chunks
                file_documents = document_processor.split_documents(
                    text=file.original_text,
                    filename=file.filename,
                    metadata=metadata,
                    file_id=file.id
                )
                merge_case_entity_index(
                    process_case,
                    file_id=file.id,
                    filename=file.filename,
                    text=file.original_text,
                )
                all_documents.extend(file_documents)
            
            if all_documents:
                logger.info(
                    f"Storing {len(all_documents)} document chunks in PGVector for case {case_id}",
                    extra={"case_id": case_id, "num_chunks": len(all_documents)}
                )
                
                collection_name = document_processor.store_in_vector_db(
                    case_id=case_id,
                    documents=all_documents,
                    db=process_db,
                    original_files=None  # Not used for PGVector
                )
                document_processor.prewarm_bm25_index(
                    case_id=case_id,
                    documents=all_documents,
                    force_rebuild=True,
                )
                
                logger.info(f"Successfully stored {len(all_documents)} document chunks in PGVector collection '{collection_name}' for case {case_id}")
            
            # Update case status to completed
            process_case.status = "completed"
            process_db.commit()
            
            logger.info(
                f"Successfully processed {len(file_names)} files for case {case_id}",
                extra={
                    "case_id": case_id,
                    "num_files": len(file_names),
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing files for case {case_id}: {e}", exc_info=True)
            try:
                process_case = process_db.query(Case).filter(Case.id == case_id).first()
                if process_case:
                    process_case.status = "failed"
                    process_db.commit()
            except:
                pass
        finally:
            process_db.close()
    
    # Add background task
    background_tasks.add_task(process_files_task)
    
    return {
        "status": "processing",
        "message": f"Обработка {len(files)} файлов начата. Это может занять несколько минут.",
        "case_id": case_id,
        "num_files": len(files)
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
    
    # Определяем content type по расширению файла
    import mimetypes
    content_type, _ = mimetypes.guess_type(file.filename)
    if not content_type:
        # Fallback для известных типов
        file_ext = file.file_type or (file.filename.split('.')[-1].lower() if '.' in file.filename else '')
        content_type_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ppt": "application/vnd.ms-powerpoint",
            "txt": "text/plain",
            "rtf": "application/rtf",
            "odt": "application/vnd.oasis.opendocument.text",
            "ods": "application/vnd.oasis.opendocument.spreadsheet",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "zip": "application/zip",
            "rar": "application/x-rar-compressed",
            "7z": "application/x-7z-compressed",
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")
    
    # Приоритет 1: Читаем файл из БД (новый способ хранения)
    if file.file_content:
        from urllib.parse import quote
        # Кодируем имя файла для поддержки кириллицы (RFC 5987)
        encoded_filename = quote(file.filename, safe='')
        content_disposition = f"inline; filename*=UTF-8''{encoded_filename}"
        
        return Response(
            content=file.file_content,
            media_type=content_type,
            headers={
                "Content-Disposition": content_disposition
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
                
                from urllib.parse import quote
                # Кодируем имя файла для поддержки кириллицы (RFC 5987)
                encoded_filename = quote(file.filename, safe='')
                content_disposition = f"inline; filename*=UTF-8''{encoded_filename}"
                
                return Response(
                    content=file_content,
                    media_type=content_type,
                    headers={
                        "Content-Disposition": content_disposition
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
    
    from urllib.parse import quote
    # Кодируем имя файла для поддержки кириллицы (RFC 5987)
    encoded_filename = quote(file.filename, safe='')
    content_disposition = f"inline; filename*=UTF-8''{encoded_filename}"
    
    return Response(
        content=file.original_text.encode('utf-8'),
        media_type="text/plain",  # Always return as text/plain for text fallback
        headers={
            "Content-Disposition": content_disposition
        }
    )


@router.put("/{case_id}/files/{file_id}/text")
async def update_case_file_text(
    case_id: str,
    file_id: str,
    body: UpdateCaseFileTextRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update UTF-8 plain text stored on a case file (original_text)."""
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    file = db.query(FileModel).filter(
        FileModel.id == file_id,
        FileModel.case_id == case_id
    ).first()
    if not file:
        raise HTTPException(status_code=404, detail="Файл не найдено")

    file.original_text = body.text
    if file.file_content is not None:
        file.file_content = body.text.encode("utf-8")
    db.commit()
    return {"id": file.id, "filename": file.filename, "updated": True}


@router.get("/{case_id}/files/{file_id}/text")
async def get_case_file_text(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Возвращает текстовый контент файла для подсветки цитат (File.original_text).

    ВАЖНО: это не "скачивание оригинала". Для бинарника используйте /content.
    Этот endpoint нужен, чтобы offsets (char_start/char_end) совпадали с текстом в UI.
    """
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")

    file = db.query(FileModel).filter(
        FileModel.id == file_id,
        FileModel.case_id == case_id
    ).first()
    if not file:
        raise HTTPException(status_code=404, detail="Файл не найден")

    text = (file.original_text or "")
    return Response(
        content=text.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Text-Source": "original_text",
            "X-Full-Text-Length": str(len(text)),
        },
    )


@router.get("/{case_id}/files/{file_id}/html")
async def get_file_html(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    force_refresh: bool = Query(False, description="Force refresh HTML cache")
) -> JSONResponse:
    """
    Get HTML representation of a file
    
    Returns cached HTML if available, otherwise converts and caches the result.
    Supports: DOCX, PDF, XLSX, XLS, PPTX, PPT, TXT
    
    Args:
        case_id: Case identifier
        file_id: File identifier
        db: Database session
        current_user: Current user
        force_refresh: Force refresh HTML cache even if cached
        
    Returns:
        JSONResponse with HTML content and cache status
    """
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
    
    # Import services
    from app.services.document_html_cache import DocumentHtmlCacheService
    from app.services.document_converter_service import DocumentConverterService
    
    cache_service = DocumentHtmlCacheService(db)
    converter_service = DocumentConverterService()
    
    # Check cache if not forcing refresh
    cached_html = None
    if not force_refresh:
        cached_html = cache_service.get_cached_html(file_id)
    
    if cached_html:
        logger.info(f"Returning cached HTML for file {file_id}")
        return JSONResponse(
            content={
                "html": cached_html,
                "cached": True,
                "file_id": file_id,
                "filename": file.filename
            }
        )
    
    # Need to convert - get file content
    file_content = None
    
    # Try to get from file_content field first
    if file.file_content:
        file_content = file.file_content
    # Fallback to file_path
    elif file.file_path:
        import os
        from app.config import config
        
        if os.path.isabs(file.file_path):
            file_full_path = file.file_path
        else:
            file_full_path = os.path.join(config.UPLOAD_DIR, file.file_path)
        
        if os.path.exists(file_full_path):
            try:
                with open(file_full_path, 'rb') as f:
                    file_content = f.read()
            except Exception as e:
                logger.error(f"Error reading file {file_full_path}: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail=f"Ошибка при чтении файла: {str(e)}"
                )
    
    if not file_content:
        raise HTTPException(
            status_code=404,
            detail="Содержимое файла недоступно для конвертации"
        )
    
    # Convert to HTML
    try:
        logger.info(f"Converting file {file_id} ({file.filename}) to HTML")
        html = converter_service.convert_to_html(
            file_content=file_content,
            filename=file.filename,
            file_type=file.file_type
        )
        
        # Cache the result
        try:
            cache_service.cache_html(file_id, html)
        except Exception as cache_error:
            logger.warning(f"Failed to cache HTML for file {file_id}: {cache_error}")
            # Continue even if caching fails
        
        logger.info(f"Successfully converted file {file_id} to HTML")
        return JSONResponse(
            content={
                "html": html,
                "cached": False,
                "file_id": file_id,
                "filename": file.filename
            }
        )
    except ValueError as e:
        logger.error(f"Conversion error for file {file_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Unexpected error converting file {file_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при конвертации файла: {str(e)}"
        )


@router.get("/{case_id}/files/{file_id}/download")
async def download_file(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Download file in original format"""
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
    
    # Определяем content type по расширению файла
    import mimetypes
    content_type, _ = mimetypes.guess_type(file.filename)
    if not content_type:
        # Fallback для известных типов
        file_ext = file.file_type or (file.filename.split('.')[-1].lower() if '.' in file.filename else '')
        content_type_map = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/vnd.ms-excel",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ppt": "application/vnd.ms-powerpoint",
            "txt": "text/plain",
            "rtf": "application/rtf",
            "odt": "application/vnd.oasis.opendocument.text",
            "ods": "application/vnd.oasis.opendocument.spreadsheet",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "webp": "image/webp",
            "zip": "application/zip",
            "rar": "application/x-rar-compressed",
            "7z": "application/x-7z-compressed",
        }
        content_type = content_type_map.get(file_ext, "application/octet-stream")
    
    # Приоритет 1: Читаем файл из БД (новый способ хранения)
    if file.file_content:
        from urllib.parse import quote
        # Кодируем имя файла для поддержки кириллицы (RFC 5987)
        encoded_filename = quote(file.filename, safe='')
        content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
        
        return Response(
            content=file.file_content,
            media_type=content_type,
            headers={
                "Content-Disposition": content_disposition
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
                
                from urllib.parse import quote
                # Кодируем имя файла для поддержки кириллицы (RFC 5987)
                encoded_filename = quote(file.filename, safe='')
                content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
                
                return Response(
                    content=file_content,
                    media_type=content_type,
                    headers={
                        "Content-Disposition": content_disposition
                    }
                )
            except Exception as e:
                logger.error(f"Error reading file {file_full_path}: {e}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Ошибка при чтении файла: {str(e)}"
                )
    
    # Fallback: return text content if original file not available
    if not file.original_text:
        raise HTTPException(
            status_code=404,
            detail="Содержимое файла недоступно"
        )
    
    from urllib.parse import quote
    # Кодируем имя файла для поддержки кириллицы (RFC 5987)
    encoded_filename = quote(file.filename, safe='')
    content_disposition = f"attachment; filename*=UTF-8''{encoded_filename}"
    
    return Response(
        content=file.original_text.encode('utf-8'),
        media_type=content_type,
        headers={
            "Content-Disposition": content_disposition
        }
    )

