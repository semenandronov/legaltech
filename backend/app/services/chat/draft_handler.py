"""
Draft Handler - Обработчик создания документов (Draft Mode)

Отвечает за:
- Создание документов через template graph
- Поиск шаблонов в кэше и ГАРАНТ
- Адаптацию шаблонов под запрос
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging

from app.services.chat.events import (
    SSESerializer,
    DocumentInfo,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class DraftHandler:
    """
    Обработчик Draft Mode (создание документов).
    
    Использует template graph для:
    1. Поиска шаблона (кэш → ГАРАНТ)
    2. Адаптации под контекст дела
    3. Создания документа в редакторе
    """
    
    def __init__(self, db: Session):
        """
        Инициализация обработчика
        
        Args:
            db: SQLAlchemy сессия
        """
        self.db = db
    
    async def handle(
        self,
        case_id: str,
        question: str,
        current_user: User,
        chat_history: Optional[str] = None,
        template_file_id: Optional[str] = None,
        template_file_content: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Обработать запрос на создание документа
        
        Args:
            case_id: ID дела
            question: Описание документа
            current_user: Текущий пользователь
            chat_history: История чата (для контекста)
            template_file_id: ID файла-шаблона (из БД)
            template_file_content: HTML контент локального файла
            
        Yields:
            SSE события
        """
        try:
            logger.info(f"[DraftHandler] Creating document for case {case_id}: {question[:100]}…")
            logger.info(f"[DraftHandler] Template file ID: {template_file_id}, content length: {len(template_file_content) if template_file_content else 0}")
            
            # Извлекаем название документа
            document_title = await self._extract_document_title(question)
            
            # Создаём и запускаем template graph
            from app.services.langchain_agents.legacy_stubs import create_template_graph, TemplateState
            
            graph = create_template_graph(self.db)
            
            # Инициализируем состояние
            initial_state: TemplateState = {
                "user_query": question,
                "case_id": case_id,
                "user_id": current_user.id,
                "cached_template": None,
                "garant_template": None,
                "template_source": None,
                "final_template": None,
                "adapted_content": None,
                "document_id": None,
                "messages": [],
                "errors": [],
                "metadata": {},
                "should_adapt": False,  # В draft mode возвращаем пустой шаблон
                "document_title": document_title,
                "template_file_id": template_file_id,
                "template_file_content": template_file_content,
                "case_context": None,
                "chat_history": chat_history
            }
            
            # Запускаем граф
            logger.info("[DraftHandler] Running template graph…")
            result = await graph.ainvoke(initial_state)
            
            # Проверяем результат
            if not result.get("document_id"):
                if result.get("errors"):
                    error_msg = "; ".join(result["errors"])
                    logger.error(f"[DraftHandler] Graph errors: {error_msg}")
                    yield SSESerializer.error(f"Ошибка создания документа: {error_msg}")
                    return
                else:
                    yield SSESerializer.error("Не удалось создать документ")
                    return
            
            # Логируем некритичные ошибки
            if result.get("errors"):
                critical_errors = [
                    err for err in result["errors"]
                    if "Нет содержимого" in err or "Ошибка при создании" in err
                ]
                if critical_errors:
                    yield SSESerializer.error("; ".join(critical_errors))
                    return
                else:
                    logger.warning(f"[DraftHandler] Non-critical warnings: {result['errors']}")
            
            # Получаем созданный документ
            from app.services.document_editor_service import DocumentEditorService
            
            doc_service = DocumentEditorService(self.db)
            document = doc_service.get_document(result["document_id"], current_user.id)
            
            if not document:
                yield SSESerializer.error("Созданный документ не найден")
                return
            
            logger.info(f"[DraftHandler] Document created: {document.id} (source: {result.get('template_source', 'unknown')})")
            
            # Отправляем событие о создании документа
            doc_preview = document.content[:500] if document.content else ''
            yield SSESerializer.document_created(
                doc_id=document.id,
                title=document.title,
                case_id=document.case_id,
                content=doc_preview
            )
            
            # Отправляем текстовое сообщение
            response_text = f'✅ Документ "{document.title}" успешно создан! Вы можете открыть его в редакторе для дальнейшего редактирования.'
            yield SSESerializer.text_delta(response_text)
            
        except Exception as e:
            logger.error(f"[DraftHandler] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка при создании документа: {str(e)}")
    
    async def _extract_document_title(self, question: str) -> str:
        """
        Извлечь название документа из описания
        
        Args:
            question: Описание документа
            
        Returns:
            Название документа (5-7 слов)
        """
        try:
            from app.services.llm_factory import create_legal_llm
            from langchain_core.messages import HumanMessage
            
            llm = create_legal_llm(temperature=0.1)
            prompt = f"Извлеки краткое название документа (максимум 5-7 слов) из описания: {question}. Ответь только названием, без дополнительных слов."
            
            response = llm.invoke([HumanMessage(content=prompt)])
            title_text = response.content if hasattr(response, 'content') else str(response)
            document_title = title_text.strip().replace('"', '').replace("'", "").strip()[:255]
            
            if not document_title or len(document_title) < 3:
                document_title = "Новый документ"
            if len(document_title) > 255:
                document_title = document_title[:252] + "…"
            
            return document_title
            
        except Exception as e:
            logger.warning(f"[DraftHandler] Error extracting title: {e}")
            return "Новый документ"


