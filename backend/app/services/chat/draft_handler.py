"""
Draft Handler - Обработчик создания документов (Draft Mode)

Отвечает за:
- Создание документов через LLM
- Поддержку файлов-шаблонов
- Сохранение в редакторе документов
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
import logging
import re

from app.services.chat.events import (
    SSESerializer,
    DocumentInfo,
)
from app.models.user import User

logger = logging.getLogger(__name__)


class DraftHandler:
    """
    Обработчик Draft Mode (создание документов).

    Генерирует документ через LLM и сохраняет в DocumentEditorService.
    """

    def __init__(self, db: Session):
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
        Обработать запрос на создание документа.

        Yields:
            SSE события
        """
        try:
            logger.info(f"[DraftHandler] Creating document for case {case_id}: {question[:100]}…")

            yield SSESerializer.reasoning(
                phase="draft",
                step=1,
                total_steps=3,
                content="Определяю название документа..."
            )

            # 1. Извлекаем название документа
            document_title = await self._extract_document_title(question)

            yield SSESerializer.reasoning(
                phase="draft",
                step=2,
                total_steps=3,
                content="Генерирую содержимое документа..."
            )

            # 2. Генерируем содержимое документа
            content = await self._generate_document_content(
                question=question,
                title=document_title,
                template_file_id=template_file_id,
                template_file_content=template_file_content,
                case_id=case_id,
            )

            if not content:
                yield SSESerializer.error("Не удалось сгенерировать содержимое документа")
                return

            yield SSESerializer.reasoning(
                phase="draft",
                step=3,
                total_steps=3,
                content="Сохраняю документ..."
            )

            # 3. Сохраняем документ
            from app.services.document_editor_service import DocumentEditorService

            doc_service = DocumentEditorService(self.db)
            document = doc_service.create_document(
                case_id=case_id,
                user_id=current_user.id,
                title=document_title,
                content=content
            )

            logger.info(f"[DraftHandler] Document created: {document.id}")

            # 4. Отправляем событие о создании документа
            doc_preview = content[:500] if content else ''
            yield SSESerializer.document_created(
                doc_id=str(document.id),
                title=document.title,
                case_id=case_id,
                content=doc_preview
            )

            response_text = f'✅ Документ "{document.title}" успешно создан! Вы можете открыть его в редакторе для дальнейшего редактирования.'
            yield SSESerializer.text_delta(response_text)

        except Exception as e:
            logger.error(f"[DraftHandler] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка при создании документа: {str(e)}")

    def _load_case_context(self, case_id: str) -> str:
        """Загрузить контекст дела: название, описание и тексты документов."""
        try:
            from app.models.case import Case, File as FileModel

            case = self.db.query(Case).filter(Case.id == case_id).first()
            if not case:
                return ""

            parts: List[str] = []

            # Название и описание дела
            if case.title:
                parts.append(f"Название дела: {case.title}")
            if case.description:
                parts.append(f"Описание дела: {case.description}")

            # Документы дела
            files = (
                self.db.query(FileModel)
                .filter(FileModel.case_id == case_id)
                .order_by(FileModel.filename)
                .all()
            )

            if files:
                parts.append("\nДОКУМЕНТЫ ДЕЛА:")
                total_chars = 0
                char_limit = 20_000  # суммарный лимит на все документы
                for f in files:
                    if not f.original_text or not f.original_text.strip():
                        continue
                    available = char_limit - total_chars
                    if available <= 0:
                        break
                    snippet = f.original_text[:available]
                    parts.append(f"--- {f.filename} ---\n{snippet}")
                    total_chars += len(snippet)

            return "\n".join(parts)

        except Exception as e:
            logger.warning(f"[DraftHandler] Failed to load case context: {e}")
            return ""

    async def _generate_document_content(
        self,
        question: str,
        title: str,
        template_file_id: Optional[str] = None,
        template_file_content: Optional[str] = None,
        case_id: Optional[str] = None,
    ) -> Optional[str]:
        """Сгенерировать HTML содержимое документа через LLM"""
        try:
            from app.services.llm_factory import create_legal_llm
            from langchain_core.messages import HumanMessage

            llm = create_legal_llm(temperature=0.2)

            # Контекст дела
            case_context = ""
            if case_id:
                raw = self._load_case_context(case_id)
                if raw:
                    case_context = f"\n\nКОНТЕКСТ ДЕЛА (используй для заполнения реквизитов и деталей):\n{raw}"
                    logger.info(f"[DraftHandler] Loaded case context: {len(raw)} chars")

            # Собираем контекст шаблона
            template_context = ""
            if template_file_content:
                template_context = f"\n\nШАБЛОН ДОКУМЕНТА (используй его как основу структуры):\n{template_file_content[:5000]}"
            elif template_file_id:
                try:
                    from app.models.case import File as FileModel
                    file_record = self.db.query(FileModel).filter(FileModel.id == template_file_id).first()
                    if file_record and file_record.original_text:
                        template_context = f"\n\nШАБЛОН ДОКУМЕНТА (используй его как основу структуры):\n{file_record.original_text[:5000]}"
                except Exception as e:
                    logger.warning(f"[DraftHandler] Failed to load template file: {e}")

            prompt = f"""Создай юридический документ на основе описания пользователя.

НАЗВАНИЕ: {title}
ОПИСАНИЕ: {question}
{case_context}
{template_context}

ИНСТРУКЦИИ:
- Создай профессиональный юридический документ в формате HTML
- Используй стандартную структуру для данного типа документа
- Включи все необходимые разделы
- Если в контексте дела есть имена сторон, реквизиты, суммы, даты — используй их в документе
- Поля, данные для которых отсутствуют в контексте, отметь как [ЗАПОЛНИТЬ]
- Используй HTML-теги для форматирования (h1, h2, p, ul, li, table и т.д.)

Ответь только HTML-кодом документа без дополнительных комментариев."""

            response = llm.invoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, 'content') else str(response)

            if not content or len(content.strip()) < 50:
                return None

            content = content.strip()

            # Strip markdown code fences if LLM wrapped output in ```html ... ```
            content = re.sub(r'^```html?\s*', '', content, flags=re.IGNORECASE)
            content = re.sub(r'\s*```$', '', content)
            content = content.strip()

            # Extract <body> inner content if LLM returned a full HTML document
            body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL | re.IGNORECASE)
            if body_match:
                content = body_match.group(1).strip()

            return content

        except Exception as e:
            logger.error(f"[DraftHandler] Error generating content: {e}", exc_info=True)
            return None
    
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


