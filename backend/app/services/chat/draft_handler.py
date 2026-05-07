"""
Draft Handler - Обработчик создания документов (Draft Mode)

Использует DraftGraphAgent (LangGraph) для итеративного сбора контекста
из документов дела перед генерацией финального документа.
"""
from typing import AsyncGenerator, Optional, List
from sqlalchemy.orm import Session
import logging
import re

from app.services.chat.events import SSESerializer
from app.models.user import User

logger = logging.getLogger(__name__)


class DraftHandler:
    """
    Обработчик Draft Mode (создание документов).

    Оркестрирует draft_graph_agent → сохраняет готовый документ в БД.
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
        template_file_content: Optional[str] = None,
        template_system_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Обработать запрос на создание документа.
        Yields SSE события (reasoning-прогресс + document_created + text_delta).
        """
        try:
            logger.info(f"[DraftHandler] case={case_id}: {question[:100]}…")

            # 1. Извлекаем название документа (быстрый LLM-вызов)
            document_title = await self._extract_document_title(question)

            # 2. Шаблон: системный id > вложение > файл из БД
            template_context, _tpl_label = self._resolve_template(
                template_system_id=template_system_id,
                template_file_id=template_file_id,
                template_file_content=template_file_content,
                user_question=question,
            )

            # 3. Запускаем граф — он yield-ит SSE reasoning-события и в конце _draft_content
            content: Optional[str] = None
            final_title = document_title

            from app.services.chat.draft_graph_agent import run_draft_graph

            async for sse_event in run_draft_graph(
                case_id=case_id,
                query=question,
                title=document_title,
                db=self.db,
                template_context=template_context,
            ):
                # Intercept the final content marker, pass everything else through
                if '"_draft_content"' in sse_event:
                    try:
                        import json
                        raw = sse_event.split("data: ", 1)[1].strip()
                        data = json.loads(raw)
                        content = data.get("content", "")
                        final_title = data.get("title", document_title) or document_title
                    except Exception as parse_err:
                        logger.warning(f"[DraftHandler] could not parse _draft_content: {parse_err}")
                    continue  # don't forward this internal event to client
                yield sse_event

            if not content:
                yield SSESerializer.error("Не удалось сгенерировать содержимое документа")
                return

            # 4. Сохраняем документ
            yield SSESerializer.reasoning(
                phase="draft_save", step=5, total_steps=5,
                content="Сохраняю документ в редактор…"
            )

            from app.services.document_editor_service import DocumentEditorService
            doc_service = DocumentEditorService(self.db)
            document = doc_service.create_document(
                case_id=case_id,
                user_id=current_user.id,
                title=final_title,
                content=content,
            )
            logger.info(f"[DraftHandler] saved document {document.id}: {final_title}")

            # 5. Уведомляем фронтенд
            yield SSESerializer.document_created(
                doc_id=str(document.id),
                title=document.title,
                case_id=case_id,
                content=content[:500],
            )
            yield SSESerializer.text_delta(
                f'✅ Документ "{document.title}" успешно создан! '
                f'Откройте его в редакторе для доработки.'
            )

        except Exception as e:
            logger.error(f"[DraftHandler] Error: {e}", exc_info=True)
            yield SSESerializer.error(f"Ошибка при создании документа: {e}")

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _extract_document_title(self, question: str) -> str:
        """Извлечь краткое название документа из запроса пользователя."""
        try:
            import asyncio
            from app.services.llm_factory import create_legal_llm
            from langchain_core.messages import HumanMessage

            llm = create_legal_llm(temperature=0.1)
            prompt = (
                f"Извлеки краткое название документа (максимум 5–7 слов) из описания: {question}. "
                "Ответь только названием, без дополнительных слов."
            )
            resp = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
            title = (resp.content if hasattr(resp, "content") else str(resp)).strip().strip('"\'')[:255]
            return title if len(title) >= 3 else "Новый документ"
        except Exception as e:
            logger.warning(f"[DraftHandler] title extraction failed: {e}")
            return "Новый документ"

    def _resolve_template(
        self,
        *,
        template_system_id: Optional[str],
        template_file_id: Optional[str],
        template_file_content: Optional[str],
        user_question: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Единая сборка текста шаблона для draft_graph_agent."""
        from app.services.draft_template_context import resolve_draft_template_context

        text, label = resolve_draft_template_context(
            self.db,
            template_system_id=template_system_id,
            template_file_content=template_file_content,
            template_file_id=template_file_id,
            user_question=user_question,
        )
        return text or "", label
