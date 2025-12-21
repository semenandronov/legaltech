"""Upload route for Legal AI Vault"""
import logging
import json
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
            
            # ВАЖНО: Сохраняем оригинальный файл для загрузки в Yandex Vector Store
            # content уже прочитан выше (await file.read()), сохраняем его в original_files
            original_files[filename] = content
            
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

            files_to_create.append(
                {
                    "case_id": case_id,
                    "filename": filename,
                    "file_type": ext.lower(),
                    "original_text": sanitize_text(text),
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
    
    case = Case(
        id=case_id,
        user_id=current_user.id,
        full_text=full_text,
        num_documents=len(file_names),
        file_names=file_names,
        title=case_title,
        description=case_description,
        case_type=case_type,
        status="pending",
        analysis_config=analysis_config
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
            file_model = FileModel(
                case_id=case_id,
                filename=file_info["filename"],
                file_type=file_info["file_type"],
                original_text=sanitize_text(file_info["original_text"]),
            )
            db.add(file_model)
            db.flush()  # Flush to get file_model.id
            
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
        logger.error(
            f"Ошибка при сохранении дела {case_id} в БД: {e}",
            extra={"case_id": case_id, "user_id": current_user.id},
            exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="Ошибка при сохранении дела. Попробуйте загрузить файлы снова."
        )

