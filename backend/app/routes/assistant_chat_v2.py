"""
Assistant Chat V2 - Упрощённый thin controller

Использует ChatOrchestrator для обработки запросов.
Этот файл содержит только роутинг и парсинг запросов.
"""
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
import logging

from app.utils.database import get_db
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.chat import (
    ChatOrchestrator,
    ChatRequest,
    get_chat_orchestrator,
    ChatHistoryService,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["assistant-chat-v2"])


def _normalize_bool(value) -> bool:
    """Нормализовать значение к bool"""
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


@router.post("/api/v2/assistant/chat")
async def assistant_chat_v2(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Streaming chat endpoint V2 (использует ChatOrchestrator)
    
    Accepts:
        - messages: array of {role, content}
        - case_id: ID дела
        - web_search: включить веб-поиск
        - legal_research: включить поиск в ГАРАНТ
        - deep_think: включить глубокое мышление
        - draft_mode: режим создания документа
        - document_context: контекст документа (для редактора)
        - document_id: ID документа
        - selected_text: выделенный текст
        - template_file_id: ID файла-шаблона
        - template_file_content: контент локального шаблона
        - attached_file_ids: прикреплённые файлы
        
    Returns:
        SSE stream с событиями
    """
    try:
        # Парсим тело запроса
        body = await request.json()
        
        # Извлекаем параметры
        messages = body.get("messages", [])
        case_id = body.get("case_id") or body.get("caseId")
        
        if not case_id:
            raise HTTPException(status_code=400, detail="case_id is required")
        
        if not messages:
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        if last_message.get("role") != "user":
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        question = last_message.get("content", "")
        
        # Нормализуем boolean параметры
        web_search = _normalize_bool(body.get("web_search", False))
        legal_research = _normalize_bool(body.get("legal_research", False))
        deep_think = _normalize_bool(body.get("deep_think", False))
        draft_mode = _normalize_bool(body.get("draft_mode", False))
        
        # Опциональные параметры
        document_context = body.get("document_context")
        document_id = body.get("document_id")
        selected_text = body.get("selected_text")
        template_file_id = body.get("template_file_id")
        template_file_content = body.get("template_file_content")
        attached_file_ids = body.get("attached_file_ids")
        
        if attached_file_ids:
            logger.info(f"Attached file IDs: {attached_file_ids}")
        
        # Создаём ChatRequest
        chat_request = ChatRequest(
            case_id=case_id,
            question=question,
            current_user=current_user,
            web_search=web_search,
            legal_research=legal_research,
            deep_think=deep_think,
            draft_mode=draft_mode,
            document_context=document_context,
            document_id=document_id,
            selected_text=selected_text,
            template_file_id=template_file_id,
            template_file_content=template_file_content,
            attached_file_ids=attached_file_ids
        )
        
        # Создаём оркестратор и обрабатываем запрос
        orchestrator = get_chat_orchestrator(db)
        
        return StreamingResponse(
            orchestrator.process_request(chat_request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in assistant_chat_v2: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v2/assistant/chat/{case_id}/sessions")
async def get_chat_sessions_v2(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить список сессий чата для дела
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Получаем сессии через сервис
        history_service = ChatHistoryService(db)
        sessions = history_service.get_sessions_for_case(case_id)
        
        return {"sessions": sessions}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting sessions: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v2/assistant/chat/{case_id}/history")
async def get_chat_history_v2(
    case_id: str,
    session_id: Optional[str] = None,
    all_sessions: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Получить историю сообщений чата
    
    Args:
        case_id: ID дела
        session_id: ID конкретной сессии (опционально)
        all_sessions: Вернуть сообщения из всех сессий
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Получаем историю через сервис
        history_service = ChatHistoryService(db)
        
        if all_sessions:
            messages = history_service.get_session_history(case_id, session_id=None)
        else:
            messages = history_service.get_session_history(case_id, session_id=session_id)
        
        # Форматируем сообщения
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "source_references": msg.source_references,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "session_id": msg.session_id
            })
        
        return {"messages": formatted_messages}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v2/assistant/chat/{case_id}/sessions/{session_id}")
async def delete_chat_session_v2(
    case_id: str,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Удалить сессию чата
    """
    try:
        from app.models.case import Case
        
        # Проверяем доступ
        case = db.query(Case).filter(
            Case.id == case_id,
            Case.user_id == current_user.id
        ).first()
        
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        
        # Удаляем сессию через сервис
        history_service = ChatHistoryService(db)
        deleted_count = history_service.delete_session(case_id, session_id)
        
        return {"deleted": deleted_count}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


