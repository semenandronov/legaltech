"""Stream hybrid draft workflow as chat SSE."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, List, Optional

from app.models.user import User
from app.services.chat.events import SSESerializer
from app.services.draft_agent.context import DraftAgentContext
from app.services.draft_agent.harness import DraftAgentHarness
from app.services.draft_agent.sse_bridge import _ToolTracker, map_draft_stream_to_sse
from app.services.draft_agent.workflow import create_draft_hybrid_graph
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_STEP_LABELS = {
    "decompose_task": ("План поиска", "Разбиваю задачу на подзапросы к материалам дела…"),
    "triage_documents": ("Триаж документов", "Отбираю релевантные файлы дела…"),
    "retrieve_materials": ("Поиск по делу", "Собираю фрагменты из документов…"),
    "parallel_extract": ("Извлечение фактов", "Извлекаю структурированные факты…"),
    "consolidate_state": ("Паспорт фактов", "Сводю факты в единый паспорт…"),
    "assess_coverage": ("Проверка полноты", "Проверяю, достаточно ли данных…"),
    "targeted_retrieval": ("Дособор фактов", "Точечный поиск по пробелам…"),
    "verify_financials": ("Калькулятор", "Верифицирую расчёты…"),
    "generate_document": ("Генерация", "Формирую черновик документа…"),
    "complete_document": ("Дозаполнение", "Проверяю и дописываю недостающие блоки…"),
    "persist": ("Сохранение", "Сохраняю документ в редактор…"),
    "catalog_fill": ("Заполнение шаблона", "Подставляю значения в поля шаблона…"),
}


class DraftAgentStreamService:
    """Runs hybrid draft workflow and yields SSE for case chat."""

    def __init__(self, db: Session):
        self.db = db

    def _emit_step(self, node: str, *, status: str, step_idx: int) -> str:
        label, content = _STEP_LABELS.get(node, (node, ""))
        return SSESerializer.assistant_activity(
            step_id=f"draft_step_{node}",
            phase=f"draft_{node}",
            step=step_idx,
            total_steps=11,
            label=label,
            content=content,
            status=status,
        )

    async def stream(
        self,
        *,
        case_id: str,
        question: str,
        user: User,
        session_id: str,
        attached_file_ids: Optional[List[str]] = None,
        template_file_id: Optional[str] = None,
        template_file_content: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        question = (question or "").strip()
        if not question:
            yield SSESerializer.error("Пустой запрос")
            return

        ctx = DraftAgentContext(
            user_id=str(user.id),
            case_id=str(case_id),
            session_id=str(session_id),
            file_ids=list(attached_file_ids or []),
            template_file_id=template_file_id,
            template_file_content=template_file_content,
        )

        harness = DraftAgentHarness(ctx, db=self.db, user_question=question)
        resolved = harness.session.template
        graph = create_draft_hybrid_graph(self.db, session=harness.session)

        pipeline_input = {
            "case_id": str(case_id),
            "user_id": str(user.id),
            "user_prompt": question,
            "attached_file_ids": list(attached_file_ids or []) or None,
            "template_mode": resolved.mode,
            "template_html": resolved.template_html or None,
            "template_label": resolved.template_label,
            "template_key": resolved.template_key,
            "brief_intent": (
                resolved.brief_intent.to_state_dict() if resolved.brief_intent else {}
            ),
            "retrieval_retry_count": 0,
            "coverage_sufficient": False,
            "errors": [],
        }

        tracker = _ToolTracker()
        todos_sent: set[str] = set()
        step_idx = 0
        final_response = ""

        logger.info(
            "[DraftAgentStream] hybrid start case=%s session=%s files=%s template_mode=%s fields=%s pipeline=%s",
            case_id,
            session_id,
            len(ctx.file_ids),
            resolved.mode,
            resolved.field_count,
            resolved.brief_intent.requires_materials_pipeline if resolved.brief_intent else False,
        )

        if resolved.has_template:
            if resolved.mode == "catalog_fill":
                tpl_content = (
                    f"«{resolved.template_label or 'Шаблон'}»: {resolved.field_count} полей "
                    f"({resolved.placeholder_summary()[:120]})"
                )
            else:
                tpl_content = (
                    f"«{resolved.template_label or 'Шаблон'}» — образец структуры "
                    f"(без плейсхолдеров, режим template_guide)"
                )
            yield SSESerializer.assistant_activity(
                step_id="draft_template_resolved",
                phase="draft_template",
                step=1,
                total_steps=11,
                label="Шаблон",
                content=tpl_content,
                status="completed",
            )

        yield SSESerializer.assistant_activity(
            step_id="draft_workflow_start",
            phase="draft_workflow",
            step=1,
            total_steps=11,
            label="Draft Workflow",
            content="Запускаю создание документа (план → поиск → проверка → документ)…",
            status="running",
        )

        try:
            async for part in graph.astream(
                pipeline_input,
                stream_mode=["updates", "custom"],
            ):
                for sse in map_draft_stream_to_sse(
                    session_id=session_id,
                    case_id=case_id,
                    raw_part=part,
                    tracker=tracker,
                    todos_sent=todos_sent,
                ):
                    yield sse

                if isinstance(part, tuple) and len(part) == 2:
                    mode, payload = part
                else:
                    continue

                if mode != "updates" or not isinstance(payload, dict):
                    continue

                for node_name, node_update in payload.items():
                    if not isinstance(node_update, dict):
                        continue
                    step_idx += 1
                    yield self._emit_step(node_name, status="running", step_idx=step_idx)

                    if node_update.get("response"):
                        final_response = str(node_update["response"])
                    if node_update.get("document_created") and not final_response:
                        doc = node_update["document_created"]
                        if isinstance(doc, dict):
                            final_response = (
                                f'✅ Документ «{doc.get("title", "Документ")}» создан.\n'
                                f"Открыть: /cases/{case_id}/editor/{doc.get('id', '')}"
                            )

                    yield self._emit_step(node_name, status="completed", step_idx=step_idx)

            if final_response:
                yield SSESerializer.text_delta(final_response)

            yield SSESerializer.assistant_activity(
                step_id="draft_workflow_start",
                phase="draft_workflow",
                step=10,
                total_steps=11,
                label="Draft Workflow",
                content="Готово" if final_response else "Завершено без текста ответа",
                status="completed" if final_response else "error",
            )
        except Exception as exc:
            logger.error("[DraftAgentStream] hybrid failed: %s", exc, exc_info=True)
            yield SSESerializer.error(f"Ошибка создания документа: {exc}")
