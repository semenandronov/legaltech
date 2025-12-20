"""Upload route for Legal AI Vault"""
import logging
import json
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Form
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
from sqlalchemy.orm import Session
from app.utils.file_parser import parse_file
from app.services.langchain_loaders import DocumentLoaderService
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, File as FileModel
from app.models.analysis import DocumentChunk
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
    langchain_documents_by_file: Dict[str, List[Document]] = {}  # Store LangChain documents

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
            
            # Combine all documents from file into single text
            text = "\n\n".join([doc.page_content for doc in langchain_docs])
            
            # Убеждаемся, что все документы имеют правильные метаданные
            for doc in langchain_docs:
                if "source_file" not in doc.metadata:
                    doc.metadata["source_file"] = filename
                # Убеждаемся, что source есть в metadata (для совместимости)
                if "source" not in doc.metadata:
                    doc.metadata["source"] = filename
            
            # Store LangChain documents for later processing
            langchain_documents_by_file[filename] = langchain_docs
            
            logger.info(
                f"Loaded {len(langchain_docs)} LangChain documents from {filename}, "
                f"total text length: {len(text)} chars"
            )
            
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
        
        # Create File entries and process with LangChain
        document_processor = DocumentProcessor()
        all_documents = []  # For LangChain
        
        for file_info in files_to_create:
            file_model = FileModel(
                case_id=case_id,
                filename=file_info["filename"],
                file_type=file_info["file_type"],
                original_text=sanitize_text(file_info["original_text"]),
            )
            db.add(file_model)
            db.flush()  # Flush to get file_model.id
            
            # Process document with LangChain
            try:
                # Use LangChain documents if available (better metadata), otherwise split manually
                if file_info["filename"] in langchain_documents_by_file and langchain_documents_by_file[file_info["filename"]]:
                    # Use documents from LangChain loader (already have metadata)
                    langchain_docs = langchain_documents_by_file[file_info["filename"]]
                    
                    # Split each LangChain document into chunks if needed
                    chunks = []
                    for langchain_doc in langchain_docs:
                        # Split large documents into smaller chunks
                        if len(langchain_doc.page_content) > 1000:
                            split_chunks = document_processor.split_documents(
                                text=langchain_doc.page_content,
                                filename=file_info["filename"],
                                metadata={
                                    **langchain_doc.metadata,  # Preserve LangChain metadata
                                    "file_id": file_model.id,
                                    "file_type": file_info["file_type"]
                                }
                            )
                            chunks.extend(split_chunks)
                        else:
                            # Use document as-is, just add file metadata
                            langchain_doc.metadata.update({
                                "file_id": file_model.id,
                                "file_type": file_info["file_type"]
                            })
                            chunks.append(langchain_doc)
                else:
                    # Fallback: split document manually
                    chunks = document_processor.split_documents(
                        text=file_info["original_text"],
                        filename=file_info["filename"],
                        metadata={
                            "file_id": file_model.id,
                            "file_type": file_info["file_type"]
                        }
                    )
                
                # Save chunks to database
                for chunk_idx, chunk_doc in enumerate(chunks):
                    # Очищаем текст чанка от NUL символов
                    sanitized_chunk_text = sanitize_text(chunk_doc.page_content)
                    
                    # Убеждаемся, что метаданные правильно установлены
                    # source_file должен быть установлен из metadata или filename
                    source_file = chunk_doc.metadata.get("source_file") or file_info["filename"]
                    
                    chunk_model = DocumentChunk(
                        case_id=case_id,
                        file_id=file_model.id,
                        chunk_index=chunk_idx,
                        chunk_text=sanitized_chunk_text,
                        source_file=source_file,
                        source_page=chunk_doc.metadata.get("source_page"),
                        source_start_line=chunk_doc.metadata.get("source_start_line"),
                        source_end_line=chunk_doc.metadata.get("source_end_line"),
                        chunk_metadata=chunk_doc.metadata
                    )
                    db.add(chunk_model)
                    # Используем очищенный текст для документов LangChain и обновляем metadata
                    chunk_doc.page_content = sanitized_chunk_text
                    # Убеждаемся, что source_file установлен в metadata
                    if "source_file" not in chunk_doc.metadata:
                        chunk_doc.metadata["source_file"] = source_file
                    all_documents.append(chunk_doc)
                    
                logger.info(
                    f"Processed {len(chunks)} chunks from LangChain for file {file_info['filename']} "
                    f"(case {case_id}, file_id {file_model.id})"
                )
            except Exception as e:
                logger.error(
                    f"Ошибка при обработке документа {file_info['filename']} через LangChain: {e}",
                    exc_info=True
                )
                raise HTTPException(
                    status_code=500,
                    detail=f"Ошибка при обработке документа '{file_info['filename']}' через LangChain: {str(e)}"
                )
        
        db.commit()
        
        # Store documents in vector database (Yandex AI Studio Index)
        if not all_documents:
            raise HTTPException(
                status_code=400,
                detail="Не удалось извлечь документы для сохранения в индекс"
            )
        
        logger.info(
            f"Storing {len(all_documents)} document chunks in Yandex Index for case {case_id}",
            extra={"case_id": case_id, "num_chunks": len(all_documents)}
        )
        index_id = document_processor.store_in_vector_db(
            case_id=case_id,
            documents=all_documents,
            db=db
        )
        logger.info(f"Successfully stored documents in Yandex Index {index_id} for case {case_id}")
        
        # Create assistant for case (after index is created)
        if not index_id:
            raise HTTPException(
                status_code=500,
                detail=f"Индекс не был создан для дела {case_id}. Невозможно создать ассистента."
            )
        
        try:
            from app.services.yandex_assistant import YandexAssistantService
            assistant_service = YandexAssistantService()
            assistant_id = assistant_service.create_assistant(case_id, index_id)
            case.yandex_assistant_id = assistant_id
            db.commit()
            logger.info(f"✅ Created assistant {assistant_id} for case {case_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create assistant for case {case_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при создании ассистента для дела: {str(e)}"
            )
        
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

