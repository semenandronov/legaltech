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
        editor_mode_hint: Optional[str] = None
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
            logger.info(f"[EditorHandler] Processing request for document {document_id}")
            logger.info(f"[EditorHandler] Document length: {len(document_context)}, selected: {len(selected_text) if selected_text else 0}")
            
            # Важно: НЕ смешиваем инструкции/данные документа с user-сообщением.
            # Документ и выделение передаются отдельными полями (document_context/selected_text),
            # а в question оставляем только намерение пользователя.
            enhanced_question = self._build_enhanced_question(
                question=question,
                selected_text=selected_text,
                editor_mode_hint=editor_mode_hint,
            )
            
            # Используем ChatGraphService вместо legacy ChatAgent
            from app.services.langchain_agents.chat_graph_service import get_chat_graph_service
            
            chat_service = get_chat_graph_service(self.db, self.rag_service)
            
            # Вызываем stream_response с document_context
            async for event in chat_service.stream_response(
                case_id=case_id,
                question=enhanced_question,
                user=current_user,
                document_context=document_context,
                document_id=document_id,
                selected_text=selected_text,
                deep_think=False,
                legal_research=False,
                draft_mode=False,
                editor_mode_hint=editor_mode_hint
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
    


