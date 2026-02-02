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
    # #region agent log
    import json as json_module
    from datetime import datetime
    def _debug_log(location, message, data, hypothesis_id="C", run_id="chat_request"):
        log_entry = json_module.dumps({
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(datetime.now().timestamp() * 1000)
        })
        try:
            with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                f.write(log_entry + '\n')
        except: pass
    # #endregion
    
    try:
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:64", "Request received", {"user_id": current_user.id if current_user else None}, hypothesis_id="C")
        except: pass
        # #endregion
        
        # Парсим тело запроса
        body = await request.json()
        
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:70", "Body parsed", {"has_messages": "messages" in body, "has_case_id": "case_id" in body or "caseId" in body}, hypothesis_id="C")
        except: pass
        # #endregion
        
        # Извлекаем параметры
        messages = body.get("messages", [])
        case_id = body.get("case_id") or body.get("caseId")
        
        if not case_id:
            # #region agent log
            try:
                _debug_log("assistant_chat_v2.py:75", "Validation failed", {"error": "case_id is required"}, hypothesis_id="C")
            except: pass
            # #endregion
            raise HTTPException(status_code=400, detail="case_id is required")
        
        if not messages:
            # #region agent log
            try:
                _debug_log("assistant_chat_v2.py:81", "Validation failed", {"error": "No messages provided"}, hypothesis_id="C")
            except: pass
            # #endregion
            raise HTTPException(status_code=400, detail="No messages provided")
        
        last_message = messages[-1]
        if last_message.get("role") != "user":
            # #region agent log
            try:
                _debug_log("assistant_chat_v2.py:87", "Validation failed", {"error": "Last message must be from user", "last_role": last_message.get("role")}, hypothesis_id="C")
            except: pass
            # #endregion
            raise HTTPException(status_code=400, detail="Last message must be from user")
        
        question = last_message.get("content", "")
        
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:93", "Question extracted", {"question_length": len(question), "case_id": case_id}, hypothesis_id="C")
        except: pass
        # #endregion
        
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
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:117", "Creating orchestrator", {"case_id": case_id}, hypothesis_id="C")
        except: pass
        # #endregion
        
        orchestrator = get_chat_orchestrator(db)
        
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:122", "Orchestrator created, starting stream", {"case_id": case_id, "question_length": len(question)}, hypothesis_id="C")
        except: pass
        # #endregion
        
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
        # #region agent log
        try:
            _debug_log("assistant_chat_v2.py:135", "HTTPException raised", {"status_code": "will_re_raise"}, hypothesis_id="C")
        except: pass
        # #endregion
        raise
    except Exception as e:
        # #region agent log
        try:
            import traceback
            _debug_log("assistant_chat_v2.py:140", "Exception caught", {"error": str(e), "error_type": type(e).__name__, "traceback": traceback.format_exc()}, hypothesis_id="C")
        except: pass
        # #endregion
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


