"""Upload route for Legal AI Vault"""
import logging
import json
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_loaders import DocumentLoaderService
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.user import User
from app.services.document_processor import DocumentProcessor
from app.services.document_classifier_service import DocumentClassifierService
from langchain_core.documents import Document
from app.config import config
import uuid

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
    
    Supports: PDF, DOCX, TXT, XLSX
    Returns: case_id, num_files, file_names, status, message
    """
    if not files:
        raise HTTPException(status_code=400, detail="Не загружено ни одного файла")
    
    # Validate file extensions
    allowed_extensions = [ext.replace(".", "") for ext in config.ALLOWED_EXTENSIONS]
    file_names: List[str] = []
    text_parts: List[str] = []
    total_text_len = 0
    files_to_create: List[dict] = []
    original_files: Dict[str, bytes] = {}  # Store original file content for Yandex Vector Store
    
    # Создаем директорию для сохранения оригинальных файлов
    upload_dir = config.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)

    # Генерируем case_id один раз, чтобы использовать его и для Case, и для File
    case_id = str(uuid.uuid4())
    
    for file in files:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Пустое имя файла недопустимо")
        
        # Sanitize filename to prevent path traversal
        filename = file.filename.replace("..", "").replace("/", "").replace("\\", "")
        if filename != file.filename:
            logger.warning(f"Sanitized filename from {file.filename} to {filename}")
        
        # Check extension
        _, ext = filename.rsplit(".", 1) if "." in filename else (filename, "")
        if ext.lower() not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Файл '{filename}' имеет неподдерживаемый формат. Поддерживаются: {', '.join(allowed_extensions)}"
            )
        
        # Check file size and read content
        content = await file.read()
        
        if len(content) == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Файл '{filename}' пуст или не может быть прочитан"
            )
        
        if len(content) > config.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Файл '{filename}' слишком большой. Максимальный размер: {config.MAX_FILE_SIZE / 1024 / 1024} МБ"
            )
        
        # Parse file using LangChain loaders
        # ВАЖНО: Используем только LangChain loaders, никаких fallback
        try:
            langchain_docs = DocumentLoaderService.load_document(content, filename)
            
            if not langchain_docs:
                raise HTTPException(
                    status_code=400,
                    detail=f"LangChain loader не вернул документы для файла '{filename}'"
                )
            
            # Combine all documents from file into single text (для валидации)
            text = "\n\n".join([doc.page_content for doc in langchain_docs])
            
            logger.info(
                f"Extracted text from {filename} using LangChain, "
                f"total text length: {len(text)} chars"
            )
            
            # Классификация документа
            file_classification = None
            try:
                logger.info(f"Classifying document: {filename}")
                classifier_service = DocumentClassifierService()
                classification_result = classifier_service.classify_document(
                    text=text,
                    filename=filename,
                    case_context=None
                )
                
                logger.info(
                    f"Classified {filename}: type={classification_result['doc_type']}, "
                    f"confidence={classification_result['confidence']:.2f}, "
                    f"needs_review={classification_result['needs_human_review']}"
                )
                
                file_classification = classification_result
            except Exception as e:
                logger.error(f"Error classifying document {filename}: {e}", exc_info=True)
                # Не прерываем загрузку при ошибке классификации
                file_classification = {
                    "doc_type": "other",
                    "tags": [],
                    "confidence": 0.0,
                    "needs_human_review": True,
                    "reasoning": f"Ошибка классификации: {str(e)}",
                    "classifier": "error"
                }
            
            # ВАЖНО: Сохраняем оригинальный файл для загрузки в Yandex Vector Store
            # content уже прочитан выше (await file.read()), сохраняем его в original_files
            original_files[filename] = content
            
            # Сохраняем оригинальный файл на диск для просмотра
            # Создаем поддиректорию для case_id
            case_upload_dir = os.path.join(upload_dir, case_id)
            os.makedirs(case_upload_dir, exist_ok=True)
            
            # Сохраняем файл
            file_path = os.path.join(case_upload_dir, filename)
            with open(file_path, 'wb') as f:
                f.write(content)
            logger.info(f"Saved original file to {file_path}")
            
            # Remove NULL bytes (PostgreSQL doesn't allow them in strings)
            text = text.replace('\x00', '')
            
            # Check if text is empty after parsing
            if not text or not text.strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"Файл '{filename}' не содержит текста или не может быть прочитан"
                )
            
            total_text_len += len(text)
            if total_text_len > config.MAX_TOTAL_TEXT_CHARS:
                raise HTTPException(
                    status_code=400,
                    detail=f"Суммарный размер текста превышает лимит {config.MAX_TOTAL_TEXT_CHARS} символов"
                )
            # Add separator with filename
            text_parts.append(f"[{filename}]\n{text}")
            file_names.append(filename)

            # Путь к сохраненному файлу (относительно upload_dir)
            relative_file_path = os.path.join(case_id, filename)
            
            files_to_create.append(
                {
                    "case_id": case_id,
                    "filename": filename,
                    "file_type": ext.lower(),
                    "original_text": sanitize_text(text),
                    "file_path": relative_file_path,  # Сохраняем путь к оригинальному файлу
                    "file_classification": file_classification,  # Добавляем классификацию
                }
            )
        except ValueError as e:
            logger.warning("Ошибка парсинга файла %s: %s", filename, e)
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.exception("Неизвестная ошибка при обработке файла %s", filename)
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при обработке файла '{filename}'. Попробуйте загрузить файл снова."
            )
    
    # Check if we have any valid text content
    if not text_parts or not any(text.strip() for text in text_parts):
        raise HTTPException(
            status_code=400,
            detail="Все загруженные файлы пусты или не содержат текста. Пожалуйста, загрузите файлы с текстовым содержимым."
        )
    
    # Combine all text
    full_text = "\n\n".join(text_parts)
    # Remove NULL bytes (PostgreSQL doesn't allow them in strings)
    full_text = full_text.replace('\x00', '')
    
    # Final check: ensure full_text is not empty
    if not full_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Не удалось извлечь текст из загруженных файлов"
        )
    
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
    
    # Create case
    logger.info(
        f"Creating case for user {current_user.id}",
        extra={
            "user_id": current_user.id,
            "case_id": case_id,
            "num_files": len(file_names),
            "total_text_length": len(full_text),
        }
    )
    
    # Убеждаемся, что full_text не пустой и не содержит NULL байты
    sanitized_full_text = sanitize_text(full_text)
    if not sanitized_full_text or not sanitized_full_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Не удалось извлечь текст из загруженных файлов"
        )
    
    # Проверяем размер full_text (PostgreSQL Text может хранить до 1GB, но лучше ограничить)
    MAX_TEXT_LENGTH = 100 * 1024 * 1024  # 100 MB
    if len(sanitized_full_text) > MAX_TEXT_LENGTH:
        logger.warning(f"Full text is very large: {len(sanitized_full_text)} bytes, truncating to {MAX_TEXT_LENGTH}")
        sanitized_full_text = sanitized_full_text[:MAX_TEXT_LENGTH]
    
    # Убеждаемся, что file_names - это список
    if not isinstance(file_names, list):
        file_names = list(file_names) if file_names else []
    
    # Валидация: убеждаемся, что у нас есть хотя бы один файл
    if not file_names:
        raise HTTPException(
            status_code=400,
            detail="Не удалось обработать ни одного файла"
        )
    
    case = Case(
        id=case_id,
        user_id=current_user.id,
        full_text=sanitized_full_text,
        num_documents=len(file_names),
        file_names=file_names,
        title=case_title[:255] if case_title else None,  # Ограничиваем длину title
        description=sanitize_text(case_description) if case_description else None,
        case_type=case_type,
        status="pending",
        analysis_config=analysis_config if analysis_config else None
    )
    
    try:
        db.add(case)
        db.flush()  # Flush to get case.id
        
        # Create File entries
        # ВАЖНО: LangChain больше НЕ используется для сохранения chunks в БД
        # LangChain использовался только для извлечения текста (уже сделано выше)
        # Оригинальные файлы загружаются напрямую в Yandex Vector Store
        document_processor = DocumentProcessor()
        
        for file_info in files_to_create:
            # Убеждаемся, что original_text не пустой
            sanitized_original_text = sanitize_text(file_info["original_text"])
            if not sanitized_original_text or not sanitized_original_text.strip():
                logger.warning(f"Skipping file {file_info['filename']} - empty text after sanitization")
                continue
            
            # Проверяем размер original_text
            MAX_FILE_TEXT_LENGTH = 50 * 1024 * 1024  # 50 MB per file
            if len(sanitized_original_text) > MAX_FILE_TEXT_LENGTH:
                logger.warning(
                    f"File {file_info['filename']} text is very large: {len(sanitized_original_text)} bytes, "
                    f"truncating to {MAX_FILE_TEXT_LENGTH}"
                )
                sanitized_original_text = sanitized_original_text[:MAX_FILE_TEXT_LENGTH]
            
            # Ограничиваем длину filename (String(255))
            filename = file_info["filename"][:255] if len(file_info["filename"]) > 255 else file_info["filename"]
            # Ограничиваем длину file_type (String(50))
            file_type = file_info["file_type"][:50] if len(file_info["file_type"]) > 50 else file_info["file_type"]
            
            # Валидация обязательных полей
            if not filename or not filename.strip():
                logger.warning(f"Skipping file with empty filename")
                continue
            if not file_type or not file_type.strip():
                logger.warning(f"Skipping file {filename} - empty file_type")
                continue
            
            try:
                file_path = file_info.get("file_path")  # Путь к оригинальному файлу
                file_model = FileModel(
                    case_id=case_id,
                    filename=filename,
                    file_type=file_type,
                    original_text=sanitized_original_text,
                    file_path=file_path,  # Сохраняем путь к оригинальному файлу
                )
                db.add(file_model)
                db.flush()  # Flush to get file_model.id
                
                # Сохраняем классификацию документа
                if file_info.get("file_classification"):
                    from app.models.analysis import DocumentClassification
                    classification = file_info["file_classification"]
                    doc_classification = DocumentClassification(
                        case_id=case_id,
                        file_id=file_model.id,
                        doc_type=classification.get("doc_type", "other"),
                        relevance_score=0,  # Можно вычислить на основе типа
                        is_privileged="false",
                        privilege_type="none",
                        key_topics=classification.get("tags", []),
                        confidence=str(classification.get("confidence", 0.0)),
                        reasoning=classification.get("reasoning", ""),
                        needs_human_review="true" if classification.get("needs_human_review", False) else "false",
                        prompt_version="v1"
                    )
                    db.add(doc_classification)
                    logger.info(f"Saved classification for file {file_model.id}: {classification.get('doc_type', 'unknown')}")
            except Exception as file_error:
                logger.error(
                    f"Error creating File model for {filename}: {file_error}",
                    exc_info=True
                )
                # Продолжаем с другими файлами, но логируем ошибку
                continue
            
            # ВАЖНО: LangChain больше НЕ используется для сохранения chunks в БД
            # LangChain использовался только для извлечения текста (уже сделано выше)
            # Оригинальные файлы загружаются напрямую в Yandex Vector Store
            # Сохраняем только информацию о файле (File model) в БД
            logger.info(
                f"Saved file info for {file_info['filename']} "
                f"(case {case_id}, file_id {file_model.id})"
            )
        
        db.commit()
        
        # Store documents in PGVector
        logger.info(
            f"Preparing documents for PGVector storage for case {case_id}",
            extra={"case_id": case_id, "num_files": len(file_names)}
        )
        
        # Create documents from all files using document_processor
        all_documents = []
        for file_info in files_to_create:
            filename = file_info["filename"]
            text = file_info["original_text"]
            
            # Split text into chunks with metadata
            file_documents = document_processor.split_documents(
                text=text,
                filename=filename,
                metadata={"case_id": case_id}
            )
            all_documents.extend(file_documents)
        
        logger.info(
            f"Storing {len(all_documents)} document chunks in PGVector for case {case_id}",
            extra={"case_id": case_id, "num_chunks": len(all_documents)}
        )
        
        collection_name = document_processor.store_in_vector_db(
            case_id=case_id,
            documents=all_documents,
            db=db,
            original_files=None  # Not used for PGVector
        )
        logger.info(f"Successfully stored {len(all_documents)} document chunks in PGVector collection '{collection_name}' for case {case_id}")
        
        # PGVector: No assistant needed, we use direct RAG with YandexGPT
        logger.info(f"PGVector: Skipping assistant creation for case {case_id} (using direct RAG)")
        
        db.refresh(case)
        
        logger.info(
            f"Successfully uploaded {len(file_names)} files for case {case_id}",
            extra={
                "case_id": case_id,
                "num_files": len(file_names),
                "user_id": current_user.id,
            }
        )
        
        return {
            "case_id": case_id,
            "num_files": len(file_names),
            "file_names": file_names,
            "status": "success",
            "message": f"Загружено {len(file_names)} файлов. Готово к чату!"
        }
    except Exception as e:
        db.rollback()
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

