"""Upload route for Legal AI Vault"""
import logging
import json
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.user import User
from app.config import config
import uuid
from app.services.langchain_loaders import DocumentLoaderService

logger = logging.getLogger(__name__)


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

router = APIRouter()


class CaseInfoRequest(BaseModel):
    """Request model for case information"""
    title: str = Field(..., min_length=1, max_length=255, description="Case title")
    description: Optional[str] = Field(None, max_length=5000, description="Case description")
    case_type: Optional[str] = Field(None, description="Case type")
    analysis_config: Optional[dict] = None
    
    @field_validator('title')
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 0:
            raise ValueError('Title cannot be empty')
        if len(v) > 255:
            raise ValueError('Title must be at most 255 characters')
        return v


@router.post("/chunk-preview")
async def chunk_preview(
    file: UploadFile = File(...),
    max_chunks: int = Form(200),
    engine: str = Form("docling"),
    current_user: User = Depends(get_current_user),
):
    """
    Preview how a single uploaded file is split into chunks by current ingestion pipeline.
    Intended for testing/tuning only.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Пустое имя файла недопустимо")

    filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
    _, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
    allowed_extensions = [e.replace(".", "") for e in config.ALLOWED_EXTENSIONS]
    if ext.lower() not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Формат '{ext}' не поддерживается. Поддерживаются: {', '.join(allowed_extensions)}",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Файл пуст")

    if len(content) > config.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Файл слишком большой. Максимум: {config.MAX_FILE_SIZE / 1024 / 1024:.0f} МБ",
        )

    safe_limit = max(1, min(int(max_chunks or 200), 1000))
    selected_engine = (engine or "docling").strip().lower()
    if selected_engine not in {"docling", "yandex"}:
        raise HTTPException(status_code=400, detail="engine должен быть 'docling' или 'yandex'")

    try:
        docs = DocumentLoaderService.load_document_for_preview(
            content=content,
            filename=filename,
            engine=selected_engine,
        )
    except Exception as e:
        logger.error("Chunk preview failed for %s by user %s: %s", filename, current_user.id, e, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать документ: {e}")

    chunks = []
    total_chars = 0
    for idx, doc in enumerate(docs[:safe_limit]):
        text = (doc.page_content or "").strip()
        chars = len(text)
        total_chars += chars
        chunks.append(
            {
                "index": idx,
                "chars": chars,
                "preview": text[:600],
                "text": text,
                "metadata": dict(doc.metadata or {}),
            }
        )

    return {
        "filename": filename,
        "engine": selected_engine,
        "content_bytes": len(content),
        "chunks_total": len(docs),
        "chunks_returned": len(chunks),
        "total_chars_returned": total_chars,
        "truncated": len(docs) > safe_limit,
        "chunks": chunks,
    }
    
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
        if v is not None:
            valid_types = ["litigation", "contracts", "dd", "compliance", "other"]
            if v not in valid_types:
                raise ValueError(f'Case type must be one of: {", ".join(valid_types)}')
        return v


# Accept both /api/upload/ and /api/upload (без слеша)
@router.post("/", include_in_schema=True)
@router.post("", include_in_schema=False)
async def upload_files(
    files: List[UploadFile] = File(...),
    case_info: Optional[str] = Form(None),  # JSON string with case info from FormData
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload files and extract text content
    
    Supports: PDF, DOCX, TXT, XLSX, CSV, изображения (PNG, JPEG, WebP, …) через Yandex Vision OCR
    Returns: case_id, num_files, file_names, status, message
    """
    if not files:
        raise HTTPException(status_code=400, detail="Не загружено ни одного файла")
    
    # Validate file extensions
    allowed_extensions = [ext.replace(".", "") for ext in config.ALLOWED_EXTENSIONS]
    file_names: List[str] = []
    files_to_create: List[dict] = []
    original_files: Dict[str, bytes] = {}

    upload_dir = config.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)

    # Генерируем case_id один раз, чтобы использовать его и для Case, и для File
    case_id = str(uuid.uuid4())
    
    # Список путей к сохранённым файлам для отката при ошибке
    saved_file_paths = []

    # Save each file immediately (bytes only); OCR runs in background
    case_upload_dir = os.path.join(upload_dir, case_id)
    os.makedirs(case_upload_dir, exist_ok=True)

    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Пустое имя файла недопустимо")

        filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
        if filename != file.filename:
            logger.warning(f"Sanitized filename from {file.filename} to {filename}")

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

        original_files[filename] = content

        file_path = os.path.join(case_upload_dir, filename)
        with open(file_path, "wb") as f:
            f.write(content)
        saved_file_paths.append(file_path)
        logger.info(f"Saved original file to {file_path}")

        file_names.append(filename)
        relative_file_path = os.path.join(case_id, filename)
        files_to_create.append(
            {
                "case_id": case_id,
                "filename": filename[:255],
                "file_type": ext.lower()[:50],
                "original_text": "",           # filled by background task
                "file_path": relative_file_path,
                "file_content": content,
                "processing_status": "pending",
            }
        )

    if not files_to_create:
        db.rollback()
        _cleanup_uploaded_files(saved_file_paths)
        raise HTTPException(status_code=400, detail="Не удалось сохранить ни одного файла")

    # Parse case info if provided
    case_title = f"Дело из {len(file_names)} документов"
    case_description = None
    case_type = None
    analysis_config = None

    if case_info:
        try:
            info_data = json.loads(case_info)
            case_title = info_data.get("title", case_title)
            case_description = info_data.get("description")
            case_type = info_data.get("case_type")
            analysis_config = info_data.get("analysis_config")
        except Exception as e:
            logger.warning(f"Ошибка при парсинге case_info: {e}")

    case = Case(
        id=case_id,
        user_id=current_user.id,
        full_text="",              # filled by background task after OCR
        num_documents=len(file_names),
        file_names=file_names,
        title=case_title[:255] if case_title else None,
        description=sanitize_text(case_description) if case_description else None,
        case_type=case_type,
        status="processing",
        analysis_config=analysis_config if analysis_config else None,
    )

    new_file_ids: List[str] = []

    try:
        db.add(case)
        db.flush()

        for file_info in files_to_create:
            filename = file_info["filename"]
            file_type = file_info["file_type"]

            if not filename.strip() or not file_type.strip():
                continue

            try:
                file_model = FileModel(
                    case_id=case_id,
                    filename=filename,
                    file_type=file_type,
                    original_text="",          # filled by background task
                    file_path=file_info.get("file_path"),
                    file_content=file_info.get("file_content"),
                    processing_status="pending",
                )
                db.add(file_model)
                db.flush()
                new_file_ids.append(file_model.id)
                logger.info(f"Queued {filename} (file_id={file_model.id}) for background processing")
            except Exception as file_error:
                logger.warning(f"Error creating File model for {filename}: {file_error}", exc_info=True)
                continue

        db.commit()
        logger.info(f"Committed case {case_id} with {len(new_file_ids)} pending files")

        # Launch background processing
        import asyncio as _asyncio
        from app.services.file_processor_bg import process_files_background

        async def _bg() -> None:
            try:
                await _asyncio.to_thread(process_files_background, new_file_ids, case_id)
            except Exception as _e:
                logger.error(f"Background processing error for case {case_id}: {_e}", exc_info=True)

        _asyncio.create_task(_bg())
        logger.info(f"Background processing started for case {case_id}")

        return {
            "case_id": case_id,
            "num_files": len(new_file_ids),
            "file_names": file_names,
            "status": "processing",
            "message": f"Загружено {len(new_file_ids)} файлов. Обработка идёт в фоне.",
        }
    except Exception as e:
        db.rollback()
        # Очищаем сохранённые файлы при ошибке
        _cleanup_uploaded_files(saved_file_paths)
        
        error_detail = str(e)
        
        # Проверяем, является ли это ошибкой SQLAlchemy
        from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError
        if isinstance(e, IntegrityError):
            error_detail = f"Ошибка целостности данных: {str(e.orig) if hasattr(e, 'orig') else str(e)}"
        elif isinstance(e, OperationalError):
            error_detail = f"Ошибка базы данных: {str(e.orig) if hasattr(e, 'orig') else str(e)}"
        elif isinstance(e, SQLAlchemyError):
            error_detail = f"Ошибка SQLAlchemy: {str(e)}"
        
        logger.error(
            f"Ошибка при сохранении дела {case_id} в БД: {error_detail}",
            extra={
                "case_id": case_id,
                "user_id": current_user.id,
                "error_type": type(e).__name__,
                "error_detail": error_detail
            },
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка при сохранении дела: {error_detail}. Попробуйте загрузить файлы снова."
        )

