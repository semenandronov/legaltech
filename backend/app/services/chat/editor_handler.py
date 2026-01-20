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
import re
import uuid

from app.services.chat.events import (
    SSESerializer,
    StructuredEdit,
)
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
        selected_text: Optional[str] = None
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
            
            # Генерируем ответ через ChatAgent
            full_response = ""
            async for chunk in self._generate_response(enhanced_question):
                full_response += chunk
                yield SSESerializer.text_delta(chunk)
            
            # Извлекаем и применяем structured edits
            structured_edits = self._extract_structured_edits(full_response, document_context)
            
            if structured_edits:
                yield SSESerializer.structured_edits([e.model_dump() for e in structured_edits])
                logger.info(f"[EditorHandler] Extracted {len(structured_edits)} edits")
                
                # Применяем изменения и отправляем edited_content
                edited_content = self._apply_edits(document_context, structured_edits)
                if edited_content and edited_content != document_context:
                    from app.services.chat.events import EditedContentEvent
                    yield EditedContentEvent(
                        edited_content=edited_content,
                        structured_edits=structured_edits
                    ).to_sse()
                    logger.info(f"[EditorHandler] Applied edits, new length: {len(edited_content)}")
            
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
    
    async def _generate_response(self, enhanced_question: str) -> AsyncGenerator[str, None]:
        """
        Генерация ответа через ChatAgent
        """
        try:
            from app.services.langchain_agents.chat_agent import ChatAgent
            
            chat_agent = ChatAgent(
                case_id="",
                rag_service=self.rag_service,
                db=self.db,
                legal_research_enabled=False
            )
            
            async for chunk in chat_agent.answer_stream(enhanced_question):
                if chunk:
                    yield chunk
                    
        except Exception as e:
            logger.error(f"[EditorHandler] ChatAgent error: {e}", exc_info=True)
            yield f"Ошибка генерации ответа: {str(e)}"
    
    def _extract_structured_edits(
        self,
        response: str,
        document_context: str
    ) -> List[StructuredEdit]:
        """
        Извлечь structured edits из ответа
        
        Returns:
            Список StructuredEdit
        """
        structured_edits = []
        
        # Ищем блоки ```edit
        edit_blocks = re.findall(r'```edit\s*\n(.*?)\n```', response, re.DOTALL)
        
        for block in edit_blocks:
            find_match = re.search(r'НАЙТИ:\s*(.+?)(?=\nЗАМЕНИТЬ:|$)', block, re.DOTALL)
            replace_match = re.search(r'ЗАМЕНИТЬ:\s*(.+?)$', block, re.DOTALL)
            
            if find_match and replace_match:
                find_text = find_match.group(1).strip()
                replace_text = replace_match.group(1).strip()
                
                # Проверяем наличие в документе
                find_pos = document_context.find(find_text)
                found_in_doc = find_pos != -1
                
                # Извлекаем контекст
                context_before = ""
                context_after = ""
                
                if found_in_doc:
                    # Контекст до (50 символов)
                    start_ctx = max(0, find_pos - 50)
                    context_before = document_context[start_ctx:find_pos]
                    if start_ctx > 0:
                        space_pos = context_before.find(' ')
                        if space_pos != -1:
                            context_before = context_before[space_pos + 1:]
                    
                    # Контекст после (50 символов)
                    end_pos = find_pos + len(find_text)
                    end_ctx = min(len(document_context), end_pos + 50)
                    context_after = document_context[end_pos:end_ctx]
                    if end_ctx < len(document_context):
                        space_pos = context_after.rfind(' ')
                        if space_pos != -1:
                            context_after = context_after[:space_pos]
                
                structured_edits.append(StructuredEdit(
                    id=f"edit-{uuid.uuid4().hex[:8]}",
                    original_text=find_text,
                    new_text=replace_text,
                    context_before=context_before,
                    context_after=context_after,
                    found_in_document=found_in_doc
                ))
                
                if found_in_doc:
                    logger.info(f"[EditorHandler] Found edit: '{find_text[:50]}…' → '{replace_text[:50]}…'")
                else:
                    logger.warning(f"[EditorHandler] Edit text not found: '{find_text[:100]}…'")
        
        return structured_edits
    
    def _apply_edits(
        self,
        document_context: str,
        edits: List[StructuredEdit]
    ) -> Optional[str]:
        """
        Применить изменения к документу
        
        Returns:
            Изменённый документ или None
        """
        modified_content = document_context
        changes_applied = 0
        
        for edit in edits:
            if edit.found_in_document:
                modified_content = modified_content.replace(edit.original_text, edit.new_text, 1)
                changes_applied += 1
        
        if changes_applied > 0:
            logger.info(f"[EditorHandler] Applied {changes_applied} edits")
            return modified_content
        
        return None


