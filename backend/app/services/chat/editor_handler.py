"""
Editor Handler - Обработчик редактирования документов

Отвечает за:
- Обработку запросов в контексте документа
- Генерацию structured edits
- Применение изменений к документу
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging

from app.services.chat.events import SSESerializer
from app.services.rag_service import RAGService
from app.models.user import User

logger = logging.getLogger(__name__)


class EditorHandler:
    """
    Обработчик запросов в режиме редактора документа.
    
    Генерирует:
    - Ответы на вопросы о документе
    - Structured edits (команды НАЙТИ/ЗАМЕНИТЬ)
    """
    
    def __init__(
        self,
        rag_service: RAGService,
        db: Session
    ):
        """
        Инициализация обработчика
        
        Args:
            rag_service: RAG сервис
            db: SQLAlchemy сессия
        """
        self.rag_service = rag_service
        self.db = db
    
    async def handle(
        self,
        case_id: str,
        question: str,
        current_user: User,
        document_id: str,
        document_context: str,
        selected_text: Optional[str] = None,
        editor_mode_hint: Optional[str] = None,
        attached_file_ids: Optional[List[str]] = None,
        deep_think: bool = False,
        legal_research: bool = False,
        session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Обработать запрос в контексте документа
        
        Args:
            case_id: ID дела
            question: Вопрос/команда пользователя
            current_user: Текущий пользователь
            document_id: ID документа
            document_context: Полный текст документа
            selected_text: Выделенный текст (опционально)
            
        Yields:
            SSE события
        """
        try:
            logger.info(
                "[EditorHandler] request document_id=%s mode_hint=%s doc_chars=%s selected_chars=%s attached=%s",
                document_id,
                editor_mode_hint,
                len(document_context or ""),
                len(selected_text or ""),
                len(attached_file_ids or []),
            )
            
            # Важно: НЕ смешиваем инструкции/данные документа с user-сообщением.
            # Документ и выделение передаются отдельными полями (document_context/selected_text),
            # а в question оставляем только намерение пользователя.
            enhanced_question = self._build_enhanced_question(
                question=question,
                selected_text=selected_text,
                editor_mode_hint=editor_mode_hint,
            )

            if document_id:
                from app.services.draft_pipeline.refactor.runner import execute_draft_refactor
                import json

                ok, msg, card, final_html = execute_draft_refactor(
                    db=self.db,
                    case_id=case_id,
                    user_id=str(current_user.id),
                    document_id=document_id,
                    user_prompt=question,
                    document_context=document_context or "",
                )
                if ok and msg:
                    yield f"data: {json.dumps({'type': 'text-delta', 'textDelta': msg}, ensure_ascii=False)}\n\n"
                    if card:
                        yield f"data: {json.dumps({'type': 'document-card', 'data': card}, ensure_ascii=False)}\n\n"
                    if final_html:
                        yield f"data: {json.dumps({'type': 'edited_content', 'edited_content': final_html}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'type': 'finish', 'finishReason': 'stop'})}\n\n"
                    return
                if msg and not ok and msg.startswith("❌"):
                    yield SSESerializer.error(msg)
                    return
            
            # Используем ChatGraphService вместо legacy ChatAgent
            from app.services.langchain_agents.chat_graph_service import get_chat_graph_service
            
            chat_service = get_chat_graph_service(self.db, self.rag_service)
            
            # Вызываем stream_response с document_context
            from app.services.chat.editor_session import resolve_editor_chat_session_id

            stable_session = resolve_editor_chat_session_id(
                user_id=str(current_user.id),
                case_id=case_id,
                document_id=document_id or "new",
                requested_session_id=session_id,
            )

            async for event in chat_service.stream_response(
                case_id=case_id,
                question=enhanced_question,
                user=current_user,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                deep_think=deep_think,
                legal_research=legal_research,
                draft_mode=False,
                editor_mode_hint=editor_mode_hint,
                attached_file_ids=attached_file_ids,
                session_id=stable_session,
                persist_history=False,
            ):
                # Обрабатываем SSE события, включая structured_edits
                # structured_edits теперь приходят из графа через SSE
                yield event
            
        except Exception as e:
            logger.error(f"[EditorHandler] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка при обработке запроса: {str(e)}")
    
    def _build_enhanced_question(
        self,
        question: str,
        selected_text: Optional[str],
        editor_mode_hint: Optional[str],
    ) -> str:
        """
        Построить user-вопрос без prompt-injection из документа.
        Документальный контекст передаётся отдельно через document_context.
        """
        q = (question or "").strip()
        if not q:
            return ""
        parts = [q]
        if editor_mode_hint:
            parts.append(f"\n\n[editor_mode_hint={editor_mode_hint}]")
        if selected_text:
            # Передаём только факт наличия выделения и небольшой фрагмент для фокуса,
            # но НЕ подмешиваем полный документ (он уже передаётся отдельно).
            preview = (selected_text or "").strip()
            if len(preview) > 1200:
                preview = preview[:1200].rstrip() + "…"
            parts.append("\n\n[selected_text_preview]\n" + preview)
        return "".join(parts)
    


