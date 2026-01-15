"""Document Editor routes for Legal AI Vault"""
import logging
import re
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import List, Optional, Dict
from datetime import datetime
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.models.case import Case, File as FileModel
from app.services.document_editor_service import DocumentEditorService
from app.services.document_ai_service import DocumentAIService
from app.services.document_export_service import DocumentExportService
from app.services.document_converter_service import DocumentConverterService
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_content_disposition(filename: str) -> Dict[str, str]:
    safe_filename = (filename or "").strip() or "document"
    ascii_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", safe_filename)
    if not ascii_filename:
        ascii_filename = "document"
    # RFC 5987 encoding for non-ASCII filenames
    encoded = quote(safe_filename, safe="")
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_filename}"; '
            f"filename*=UTF-8''{encoded}"
        )
    }


class DocumentCreateRequest(BaseModel):
    """Request model for creating a document"""
    case_id: str = Field(..., min_length=1, description="Case identifier")
    title: str = Field(..., min_length=1, max_length=255, description="Document title")
    initial_content: Optional[str] = Field(None, description="Initial HTML content")
    metadata: Optional[dict] = None


class DocumentUpdateRequest(BaseModel):
    """Request model for updating a document"""
    content: str = Field(..., description="HTML content")
    title: Optional[str] = Field(None, max_length=255, description="Document title")


class AIAssistRequest(BaseModel):
    """Request model for AI assistance"""
    command: str = Field(..., description="AI command: create_contract, check_risks, improve, rewrite, simplify, custom")
    selected_text: str = Field("", description="Selected text from editor")
    prompt: str = Field("", description="Custom prompt for AI")


class DocumentResponse(BaseModel):
    """Response model for document"""
    id: str
    case_id: str
    user_id: str
    title: str
    content: str
    content_plain: Optional[str]
    metadata: Optional[dict]
    version: int
    created_at: str
    updated_at: str


class AIAssistResponse(BaseModel):
    """Response model for AI assistance"""
    result: str
    suggestions: List[str] = []


@router.post("/create", response_model=DocumentResponse)
async def create_document(
    request: DocumentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new document
    
    Args:
        request: Document creation request
        db: Database session
        current_user: Current user
        
    Returns:
        Created document
    """
    try:
        logger.info(f"Creating document: case_id={request.case_id}, user_id={current_user.id}, title={request.title}")
        # Verify case exists and user has access
        case = db.query(Case).filter(
            Case.id == request.case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Дело не найдено или доступ запрещен")
        
        # Create document
        service = DocumentEditorService(db)
        try:
            document = service.create_document(
                case_id=request.case_id,
                user_id=current_user.id,
                title=request.title,
                content=request.initial_content or "",
                metadata=request.metadata
            )
            logger.info(f"Document created successfully: {document.id}")
        except Exception as create_error:
            logger.error(f"Error in create_document service: {create_error}", exc_info=True)
            raise
        
        return DocumentResponse(
            id=document.id,
            case_id=document.case_id,
            user_id=document.user_id,
            title=document.title,
            content=document.content,
            content_plain=document.content_plain,
            metadata=document.document_metadata,
            version=document.version,
            created_at=document.created_at.isoformat() if document.created_at else datetime.utcnow().isoformat(),
            updated_at=document.updated_at.isoformat() if document.updated_at else datetime.utcnow().isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при создании документа")


@router.post("/create-from-file/{file_id}", response_model=DocumentResponse)
async def create_document_from_file(
    file_id: str,
    request: DocumentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new document in editor from an uploaded file
    
    Converts file to HTML and creates editable document.
    
    Args:
        file_id: File identifier to convert
        request: Document creation request (case_id, title)
        db: Database session
        current_user: Current user
        
    Returns:
        Created document with HTML content from file
    """
    try:
        # Verify case exists and user has access
        case = db.query(Case).filter(
            Case.id == request.case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Дело не найдено или доступ запрещен")
        
        # Get file
        file = db.query(FileModel).filter(
            FileModel.id == file_id,
            FileModel.case_id == request.case_id
        ).first()
        
        if not file:
            raise HTTPException(status_code=404, detail="Файл не найден")
        
        # Get file content
        file_content = None
        if file.file_content:
            file_content = file.file_content
        elif file.file_path:
            import os
            from app.config import config
            
            if os.path.isabs(file.file_path):
                file_full_path = file.file_path
            else:
                file_full_path = os.path.join(config.UPLOAD_DIR, file.file_path)
            
            if os.path.exists(file_full_path):
                with open(file_full_path, 'rb') as f:
                    file_content = f.read()
        
        if not file_content:
            raise HTTPException(status_code=404, detail="Содержимое файла недоступно")
        
        # Convert to HTML
        converter_service = DocumentConverterService()
        try:
            html_content = converter_service.convert_to_html(
                file_content=file_content,
                filename=file.filename,
                file_type=file.file_type
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error converting file {file_id} to HTML: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Ошибка при конвертации файла: {str(e)}")
        
        # Create document with HTML content
        doc_service = DocumentEditorService(db)
        document = doc_service.create_document(
            case_id=request.case_id,
            user_id=current_user.id,
            title=request.title or file.filename,
            content=html_content,
            metadata={
                "source_file_id": file_id,
                "source_filename": file.filename,
                "source_file_type": file.file_type
            }
        )
        
        logger.info(f"Created document {document.id} from file {file_id}")
        
        return DocumentResponse(
            id=document.id,
            case_id=document.case_id,
            user_id=document.user_id,
            title=document.title,
            content=document.content,
            content_plain=document.content_plain,
            metadata=document.document_metadata,
            version=document.version,
            created_at=document.created_at.isoformat() if document.created_at else datetime.utcnow().isoformat(),
            updated_at=document.updated_at.isoformat() if document.updated_at else datetime.utcnow().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating document from file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при создании документа из файла")


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a document by ID
    
    Args:
        document_id: Document identifier
        db: Database session
        current_user: Current user
        
    Returns:
        Document
    """
    try:
        service = DocumentEditorService(db)
        document = service.get_document(document_id, current_user.id)
        
        if not document:
            raise HTTPException(status_code=404, detail="Документ не найден")
        
        return DocumentResponse(
            id=document.id,
            case_id=document.case_id,
            user_id=document.user_id,
            title=document.title,
            content=document.content,
            content_plain=document.content_plain,
            metadata=document.document_metadata,
            version=document.version,
            created_at=document.created_at.isoformat() if document.created_at else datetime.utcnow().isoformat(),
            updated_at=document.updated_at.isoformat() if document.updated_at else datetime.utcnow().isoformat()
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при получении документа")


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: str,
    request: DocumentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update a document
    
    Args:
        document_id: Document identifier
        request: Document update request
        db: Database session
        current_user: Current user
        
    Returns:
        Updated document
    """
    try:
        service = DocumentEditorService(db)
        document = service.update_document(
            document_id=document_id,
            user_id=current_user.id,
            content=request.content,
            title=request.title
        )
        
        return DocumentResponse(
            id=document.id,
            case_id=document.case_id,
            user_id=document.user_id,
            title=document.title,
            content=document.content,
            content_plain=document.content_plain,
            metadata=document.document_metadata,
            version=document.version,
            created_at=document.created_at.isoformat() if document.created_at else datetime.utcnow().isoformat(),
            updated_at=document.updated_at.isoformat() if document.updated_at else datetime.utcnow().isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при обновлении документа")


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Delete a document
    
    Args:
        document_id: Document identifier
        db: Database session
        current_user: Current user
        
    Returns:
        Success message
    """
    try:
        service = DocumentEditorService(db)
        deleted = service.delete_document(document_id, current_user.id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Документ не найден")
        
        return {"success": True, "message": "Документ удален"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при удалении документа")


@router.get("/case/{case_id}", response_model=List[DocumentResponse])
async def list_documents(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List documents for a case
    
    Args:
        case_id: Case identifier
        db: Database session
        current_user: Current user
        
    Returns:
        List of documents
    """
    try:
        # Verify case access
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Дело не найдено")
        
        logger.info(f"Listing documents for case {case_id}, user {current_user.id}")
        service = DocumentEditorService(db)
        try:
            documents = service.list_documents(case_id, current_user.id)
            logger.info(f"Found {len(documents)} documents")
        except Exception as list_error:
            logger.error(f"Error in list_documents: {list_error}", exc_info=True)
            raise
        
        return [
            DocumentResponse(
                id=doc.id,
                case_id=doc.case_id,
                user_id=doc.user_id,
                title=doc.title,
                content=doc.content,
                content_plain=doc.content_plain,
                metadata=doc.document_metadata,
                version=doc.version,
                created_at=doc.created_at.isoformat() if doc.created_at else datetime.utcnow().isoformat(),
                updated_at=doc.updated_at.isoformat() if doc.updated_at else datetime.utcnow().isoformat()
            )
            for doc in documents
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing documents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при получении списка документов")


@router.post("/{document_id}/ai-assist", response_model=AIAssistResponse)
async def ai_assist(
    document_id: str,
    request: AIAssistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    AI assistance for document editing
    
    Args:
        document_id: Document identifier
        request: AI assistance request
        db: Database session
        current_user: Current user
        
    Returns:
        AI assistance result
    """
    try:
        # Get document
        doc_service = DocumentEditorService(db)
        document = doc_service.get_document(document_id, current_user.id)
        
        if not document:
            raise HTTPException(status_code=404, detail="Документ не найден")
        
        # Get AI assistance
        ai_service = DocumentAIService(db)
        
        # Если команда create_contract, используем template graph
        if request.command == "create_contract":
            result = await ai_service.generate_contract(
                prompt=request.prompt,
                case_id=document.case_id,
                user_id=current_user.id,
                document_id=document_id
            )
            # Преобразуем результат в формат ai_assist
            result = {
                "result": result.get("result", ""),
                "suggestions": result.get("suggestions", [])
            }
        else:
            result = ai_service.ai_assist(
                command=request.command,
                selected_text=request.selected_text,
                case_id=document.case_id,
                document_content=document.content,
                prompt=request.prompt
            )
        
        return AIAssistResponse(
            result=result.get("result", ""),
            suggestions=result.get("suggestions", [])
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in AI assist: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при выполнении AI команды: {str(e)}")


@router.post("/{document_id}/export/docx")
async def export_docx(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export document to DOCX format
    
    Args:
        document_id: Document identifier
        db: Database session
        current_user: Current user
        
    Returns:
        DOCX file
    """
    try:
        logger.info(f"Exporting document {document_id} to DOCX for user {current_user.id}")
        
        # First check if document exists
        doc_service = DocumentEditorService(db)
        document = doc_service.get_document(document_id, current_user.id)
        if not document:
            logger.warning(f"Document {document_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail=f"Документ {document_id} не найден")
        
        export_service = DocumentExportService(db)
        buffer = export_service.export_to_docx(document_id, current_user.id)
        
        filename = f"{document.title if document else 'document'}.docx"
        
        logger.info(f"Successfully exported document {document_id} to DOCX, filename: {filename}")
        
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers=_build_content_disposition(filename)
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"ValueError exporting to DOCX: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting to DOCX: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при экспорте в DOCX: {str(e)}")


@router.post("/{document_id}/export/pdf")
async def export_pdf(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Export document to PDF format
    
    Args:
        document_id: Document identifier
        db: Database session
        current_user: Current user
        
    Returns:
        PDF file
    """
    try:
        logger.info(f"Exporting document {document_id} to PDF for user {current_user.id}")
        
        # First check if document exists
        doc_service = DocumentEditorService(db)
        document = doc_service.get_document(document_id, current_user.id)
        if not document:
            logger.warning(f"Document {document_id} not found for user {current_user.id}")
            raise HTTPException(status_code=404, detail=f"Документ {document_id} не найден")
        
        export_service = DocumentExportService(db)
        buffer = export_service.export_to_pdf(document_id, current_user.id)
        
        filename = f"{document.title if document else 'document'}.pdf"
        
        logger.info(f"Successfully exported document {document_id} to PDF, filename: {filename}")
        
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers=_build_content_disposition(filename)
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"ValueError exporting to PDF: {e}", exc_info=True)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error exporting to PDF: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при экспорте в PDF: {str(e)}")


class DocumentVersionResponse(BaseModel):
    """Response model for document version"""
    id: str
    document_id: str
    content: str
    version: int
    created_at: str
    created_by: Optional[str]


@router.get("/{document_id}/versions", response_model=List[DocumentVersionResponse])
async def list_versions(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    List versions for a document
    
    Args:
        document_id: Document identifier
        db: Database session
        current_user: Current user
        
    Returns:
        List of document versions
    """
    try:
        service = DocumentEditorService(db)
        versions = service.get_versions(document_id, current_user.id)
        
        return [
            DocumentVersionResponse(
                id=version.id,
                document_id=version.document_id,
                content=version.content,
                version=version.version,
                created_at=version.created_at.isoformat() if version.created_at else datetime.utcnow().isoformat(),
                created_by=version.created_by
            )
            for version in versions
        ]
    except Exception as e:
        logger.error(f"Error listing versions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при получении версий")


@router.get("/{document_id}/versions/{version}", response_model=DocumentVersionResponse)
async def get_version(
    document_id: str,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get a specific version of a document
    
    Args:
        document_id: Document identifier
        version: Version number
        db: Database session
        current_user: Current user
        
    Returns:
        Document version
    """
    try:
        service = DocumentEditorService(db)
        versions = service.get_versions(document_id, current_user.id)
        
        version_record = next((v for v in versions if v.version == version), None)
        
        if not version_record:
            raise HTTPException(status_code=404, detail=f"Версия {version} не найдена")
        
        return DocumentVersionResponse(
            id=version_record.id,
            document_id=version_record.document_id,
            content=version_record.content,
            version=version_record.version,
            created_at=version_record.created_at.isoformat() if version_record.created_at else datetime.utcnow().isoformat(),
            created_by=version_record.created_by
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при получении версии")


@router.post("/{document_id}/restore/{version}", response_model=DocumentResponse)
async def restore_version(
    document_id: str,
    version: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Restore a document to a specific version
    
    Args:
        document_id: Document identifier
        version: Version number to restore
        db: Database session
        current_user: Current user
        
    Returns:
        Restored document
    """
    try:
        service = DocumentEditorService(db)
        document = service.restore_version(document_id, current_user.id, version)
        
        return DocumentResponse(
            id=document.id,
            case_id=document.case_id,
            user_id=document.user_id,
            title=document.title,
            content=document.content,
            content_plain=document.content_plain,
            metadata=document.document_metadata,
            version=document.version,
            created_at=document.created_at.isoformat() if document.created_at else datetime.utcnow().isoformat(),
            updated_at=document.updated_at.isoformat() if document.updated_at else datetime.utcnow().isoformat()
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error restoring version: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при восстановлении версии")


class DocumentChatRequest(BaseModel):
    """Request model for document chat"""
    question: str = Field(..., min_length=1, description="User question or instruction")


class DocumentChatResponse(BaseModel):
    """Response model for document chat"""
    answer: str
    citations: List[Dict[str, str]] = []
    suggestions: List[str] = []
    edited_content: Optional[str] = None


@router.post("/{document_id}/chat", response_model=DocumentChatResponse)
async def chat_over_document(
    document_id: str,
    request: DocumentChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Chat over document - ask questions and get AI assistance for editing
    
    Args:
        document_id: Document identifier (может быть "new" для создания нового документа)
        request: Chat request with question
        db: Database session
        current_user: Current user
        
    Returns:
        Chat response with answer and suggestions
    """
    try:
        doc_service = DocumentEditorService(db)
        document = None
        case_id = None
        
        # Если document_id не "new", получаем существующий документ
        if document_id != "new":
            document = doc_service.get_document(document_id, current_user.id)
            if not document:
                raise HTTPException(status_code=404, detail="Документ не найден")
            case_id = document.case_id
            document_content = document.content
        else:
            # Для нового документа нужно получить case_id из запроса или создать документ
            # В этом случае case_id должен быть в metadata запроса или мы создаем документ
            # Пока используем пустой контент
            document_content = ""
            # case_id должен быть передан в metadata или через отдельный параметр
            # Для упрощения, если document_id="new", создаем документ через template graph
        
        # Get AI chat response
        ai_service = DocumentAIService(db)
        
        # Если document_id="new", нужен case_id для создания документа
        # Для упрощения, если document_id="new" и нет документа, возвращаем ошибку
        # В реальности case_id должен передаваться через query параметр или в теле запроса
        if document_id == "new" and not case_id:
            raise HTTPException(status_code=400, detail="case_id required for creating new document. Use existing document_id or provide case_id.")
        
        result = await ai_service.chat_over_document(
            document_id=document_id if document_id != "new" else None,
            document_content=document_content,
            case_id=case_id or (document.case_id if document else None),
            question=request.question,
            user_id=current_user.id
        )
        
        response = DocumentChatResponse(
            answer=result.get("answer", ""),
            citations=result.get("citations", []),
            suggestions=result.get("suggestions", []),
            edited_content=result.get("edited_content")
        )
        
        # Если создан новый документ, добавляем его ID в метаданные ответа
        if result.get("new_document_id"):
            logger.info(f"New document created: {result.get('new_document_id')}")
        
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in chat over document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка при обработке запроса: {str(e)}")


class TemplateUploadResponse(BaseModel):
    """Response model for template file upload"""
    content: str  # HTML content
    filename: str
    file_type: str


@router.post("/upload-template", response_model=TemplateUploadResponse)
async def upload_template_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Upload and convert a template file to HTML (temporary, not saved to DB)
    
    This endpoint is used for draft mode when user wants to use a local file
    as a template without uploading it to the case first.
    
    Args:
        file: Template file to convert
        db: Database session
        current_user: Current user
        
    Returns:
        HTML content and file metadata
    """
    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="Имя файла не указано")
        
        # Read file content
        file_content = await file.read()
        
        if len(file_content) == 0:
            raise HTTPException(status_code=400, detail="Файл пуст")
        
        # Determine file type from filename
        _, ext = file.filename.rsplit(".", 1) if "." in file.filename else (file.filename, "")
        file_type = ext.lower()
        
        # Convert to HTML
        converter = DocumentConverterService()
        try:
            html_content = converter.convert_to_html(
                file_content=file_content,
                filename=file.filename,
                file_type=file_type
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error converting template file {file.filename}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Ошибка при конвертации файла: {str(e)}")
        
        logger.info(f"Successfully converted template file {file.filename} to HTML")
        
        return TemplateUploadResponse(
            content=html_content,
            filename=file.filename,
            file_type=file_type
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading template file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при загрузке файла-шаблона")

