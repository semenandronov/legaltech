"""Chat route for Legal AI Vault"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from app.utils.database import get_db
from app.models.case import Case, ChatMessage
from app.config import config
from openai import OpenAI
import re

router = APIRouter()

# Initialize OpenAI client
client = None
if config.OPENAI_API_KEY:
    client = OpenAI(api_key=config.OPENAI_API_KEY)


class ChatRequest(BaseModel):
    """Request model for chat"""
    case_id: str
    question: str


class ChatResponse(BaseModel):
    """Response model for chat"""
    answer: str
    sources: List[str]
    status: str


def extract_sources(text: str) -> List[str]:
    """Extract source file names from text using regex"""
    # Pattern: [filename.ext] or [filename]
    pattern = r'\[([^\]]+\.(pdf|docx|txt|xlsx))\]'
    matches = re.findall(pattern, text, re.IGNORECASE)
    sources = [match[0] for match in matches]
    # Remove duplicates while preserving order
    seen = set()
    unique_sources = []
    for source in sources:
        if source.lower() not in seen:
            seen.add(source.lower())
            unique_sources.append(source)
    return unique_sources


@router.post("/", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    Send question to ChatGPT based on case documents
    
    Returns: answer, sources, status
    """
    # Get case
    case = db.query(Case).filter(Case.id == request.case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    
    # Get chat history
    history_messages = db.query(ChatMessage).filter(
        ChatMessage.case_id == request.case_id
    ).order_by(ChatMessage.created_at.asc()).all()
    
    # Build system prompt
    system_prompt = f"""Ты эксперт по анализу юридических дел.
Текст документов дела:

{case.full_text}

Отвечай на вопрос на основе этих документов.
ВСЕГДА указывай источник (имя файла) в скобках, например [contract.pdf].
Если информации нет в документах - скажи честно.
Не давай юридических советов, только анализ фактов из документов."""
    
    # Build messages for OpenAI
    messages = [{"role": "system", "content": system_prompt}]
    
    # Add history
    for msg in history_messages:
        messages.append({"role": msg.role, "content": msg.content})
    
    # Add current question
    messages.append({"role": "user", "content": request.question})
    
    if not client:
        raise HTTPException(
            status_code=500,
            detail="OpenAI API ключ не настроен. Проверьте конфигурацию сервера."
        )
    
    try:
        # Call OpenAI API
        response = client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        
        answer = response.choices[0].message.content.strip()
        
        # Extract sources from answer
        sources = extract_sources(answer)
        
        # Save user message
        user_message = ChatMessage(
            case_id=request.case_id,
            role="user",
            content=request.question
        )
        db.add(user_message)
        
        # Save assistant message
        assistant_message = ChatMessage(
            case_id=request.case_id,
            role="assistant",
            content=answer,
            source_references=sources
        )
        db.add(assistant_message)
        
        db.commit()
        
        return ChatResponse(
            answer=answer,
            sources=sources,
            status="success"
        )
        
    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "api key" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Ошибка аутентификации OpenAI API. Проверьте API ключ."
            )
        elif "rate limit" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Превышен лимит запросов к OpenAI API. Попробуйте позже."
            )
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при обращении к OpenAI API: {str(e)}"
            )


@router.get("/{case_id}/history")
async def get_history(
    case_id: str,
    db: Session = Depends(get_db)
):
    """
    Get chat history for a case
    
    Returns: list of messages with role, content, sources, created_at
    """
    # Check if case exists
    case = db.query(Case).filter(Case.id == case_id).first()
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

