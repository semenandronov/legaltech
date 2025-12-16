"""Chat route for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.case import Case, ChatMessage
from app.models.user import User
from app.services.rag_service import RAGService
from app.services.langchain_memory import MemoryService
from app.config import config
import re
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize RAG service
rag_service = RAGService()
memory_service = MemoryService()


class ChatRequest(BaseModel):
    """Request model for chat"""
    case_id: str = Field(..., min_length=1, description="Case identifier")
    question: str = Field(..., min_length=1, max_length=5000, description="User question")
    
    @field_validator('question')
    @classmethod
    def validate_question(cls, v: str) -> str:
        v = v.strip()
        if len(v) == 0:
            raise ValueError('Question cannot be empty')
        if len(v) > 5000:
            raise ValueError('Question must be at most 5000 characters')
        return v


class ChatResponse(BaseModel):
    """Response model for chat"""
    answer: str
    sources: List[Dict[str, Any]]  # Changed to dict with detailed source info
    status: str


def format_source_reference(source: Dict[str, Any]) -> str:
    """Format source reference for display"""
    file = source.get("file", "unknown")
    page = source.get("page")
    start_line = source.get("start_line")
    
    ref = f"[Документ: {file}"
    if page:
        ref += f", стр. {page}"
    if start_line:
        ref += f", строки {start_line}"
        if source.get("end_line") and source.get("end_line") != start_line:
            ref += f"-{source.get('end_line')}"
    ref += "]"
    return ref


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Send question to ChatGPT based on case documents
    
    Returns: answer, sources, status
    """
    # Get case and verify ownership
    case = db.query(Case).filter(
        Case.id == request.case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get chat history
    history_messages = db.query(ChatMessage).filter(
        ChatMessage.case_id == request.case_id
    ).order_by(ChatMessage.created_at.asc()).all()

    # Format history for RAG
    chat_history = [
        {"role": msg.role, "content": msg.content}
        for msg in history_messages[-10:]  # Last 10 messages
    ]
    
    # Load history into memory
    if chat_history:
        memory_service.load_history_into_memory(
            request.case_id,
            chat_history,
            memory_type="summary"
        )
    
    try:
        logger.info(
            f"Processing chat request for case {request.case_id}",
            extra={
                "case_id": request.case_id,
                "user_id": current_user.id,
                "question_length": len(request.question),
                "history_length": len(chat_history),
            }
        )
        
        # Use RAG service to generate answer with sources and memory
        answer, sources = rag_service.generate_answer(
            case_id=request.case_id,
            query=request.question,
            chat_history=chat_history,
            k=5,  # Retrieve top 5 relevant chunks
            retrieval_strategy="multi_query",  # Use improved retrieval
            use_memory=True  # Use memory for context
        )
        
        # Save context to memory
        memory_service.save_context(
            request.case_id,
            request.question,
            answer,
            memory_type="summary"
        )
        
        logger.info(
            f"Successfully generated answer for case {request.case_id}",
            extra={
                "case_id": request.case_id,
                "answer_length": len(answer),
                "num_sources": len(sources),
            }
        )
        
        # Ensure answer contains source references
        if sources:
            # Add source references to answer if not already present
            source_refs = "\n\n**Источники:**\n"
            for i, source in enumerate(sources, 1):
                source_ref = format_source_reference(source)
                source_refs += f"{i}. {source_ref}\n"
            answer += source_refs
        
        # Save user message
        user_message = ChatMessage(
            case_id=request.case_id,
            role="user",
            content=request.question
        )
        db.add(user_message)
        
        # Save assistant message
        # Extract source file names for backward compatibility
        source_file_names = [s.get("file", "") for s in sources]
        assistant_message = ChatMessage(
            case_id=request.case_id,
            role="assistant",
            content=answer,
            source_references=source_file_names
        )
        db.add(assistant_message)
        
        db.commit()
        
        return ChatResponse(
            answer=answer,
            sources=sources,  # Return detailed source info
            status="success"
        )
        
    except Exception as e:
        logger.error(f"Ошибка при генерации ответа через RAG: {e}")
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Ошибка аутентификации OpenRouter API. Проверьте API ключ."
            )
        elif "rate limit" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Превышен лимит запросов к OpenRouter API. Попробуйте позже."
            )
        elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Превышено время ожидания ответа от OpenRouter API. "
                "Попробуйте упростить запрос или повторить попытку позже."
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при генерации ответа: {str(e)}"
            )


@router.get("/{case_id}/history")
async def get_history(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get chat history for a case
    
    Returns: list of messages with role, content, sources, created_at
    """
    # Check if case exists and verify ownership
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.user_id == current_user.id
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get messages
    messages = db.query(ChatMessage).filter(
        ChatMessage.case_id == case_id
    ).order_by(ChatMessage.created_at.asc()).all()
    
    return {
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "sources": msg.source_references or [],
                "created_at": msg.created_at.isoformat()
            }
            for msg in messages
        ]
    }

