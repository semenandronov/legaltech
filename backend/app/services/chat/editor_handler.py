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
            
            # Формируем enhanced question с контекстом документа
            enhanced_question = self._build_enhanced_question(
                question=question,
                document_context=document_context,
                selected_text=selected_text
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
        document_context: str,
        selected_text: Optional[str]
    ) -> str:
        """
        Построить enhanced question с контекстом документа
        """
        context_parts = []
        
        # Добавляем документ (с лимитом)
        doc_limit = 15000
        doc_preview = document_context[:doc_limit]
        context_parts.append(f"\n\n=== ПОЛНЫЙ ТЕКСТ ДОКУМЕНТА В РЕДАКТОРЕ ===\n{doc_preview}")
        if len(document_context) > doc_limit:
            context_parts.append(f"\n[… документ обрезан, показано {doc_limit} из {len(document_context)} символов …]")
        
        # Добавляем выделенный текст
        if selected_text:
            context_parts.append(f"\n\n=== ВЫДЕЛЕННЫЙ ТЕКСТ (фокус внимания) ===\n{selected_text}")
        
        # Инструкции для редактирования
        editor_instructions = """

=== РЕЖИМ РЕДАКТОРА ДОКУМЕНТА ===

Ты можешь отвечать на вопросы о документе и вносить точечные правки.

ФОРМАТ ОТВЕТА ПРИ РЕДАКТИРОВАНИИ:
1. Объясни какие изменения нужно внести
2. Укажи ТОЧНУЮ команду замены:

```edit
НАЙТИ: <точный текст из документа>
ЗАМЕНИТЬ: <новый текст>
```

ПРИМЕР:
Пользователь: 'Добавь номер 123'
Ответ: 'Добавляю номер в заголовок.
```edit
НАЙТИ: Договор поставки
ЗАМЕНИТЬ: Договор поставки №123
```'

ВАЖНО: В НАЙТИ указывай ТОЧНЫЙ текст из документа!
Если просто вопрос — отвечай без блока edit.
"""
        context_parts.append(editor_instructions)
        
        return question + "".join(context_parts)
    


