"""Tabular Chat service for analyzing table data"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Literal, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.config import config
from app.models.tabular_review import TabularReview
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.llm_streaming import async_iter_llm_text_chunks
from app.services.chat.response_shape import case_assistant_readability_base
from app.services.llm_factory import create_llm
from app.services.tabular_review_service import TabularReviewService
import logging

logger = logging.getLogger(__name__)

_EMPTY_CELL_MARKERS = frozenset({"", "-", "—", "n/a", "na", "н/д", "н/а"})


def tabular_chat_session_id(review_id: str) -> str:
    return f"tabular:{review_id}"


def _history_turn_limit() -> int:
    return max(4, int(getattr(config, "GLOBAL_ASSISTANT_HISTORY_PROMPT_MAX_TURNS", 16) or 16))


def format_cell_display(cell: Optional[Dict[str, Any]]) -> str:
    if not cell:
        return "— (пусто)"
    raw = cell.get("cell_value")
    status = str(cell.get("status") or "pending").lower()
    if raw is None or str(raw).strip() == "":
        if status in ("pending", "processing"):
            return "— (не заполнено)"
        return "— (пусто)"
    text = str(raw).strip()
    if text.lower() in _EMPTY_CELL_MARKERS:
        return "N/A (нет в документе)"
    return text


class TabularChatStreamEvent(TypedDict, total=False):
    type: Literal["text_delta", "done", "error"]
    text: str
    answer: str
    citations: List[Dict[str, str]]
    table_stats: Dict[str, int]
    message: str


class TabularChatService:
    """Service for chat over table functionality"""

    def __init__(self, db: Session):
        self.db = db
        self.tabular_service = TabularReviewService(db)
        self.history_service = ChatHistoryService(db)

        try:
            self.llm = create_llm(temperature=0.2)
        except Exception as e:
            self.llm = None
            logger.warning("GigaChat not configured: %s, tabular chat will not work", e)

    def _get_review_for_user(self, review_id: str, user_id: str) -> TabularReview:
        review = (
            self.db.query(TabularReview)
            .filter(and_(TabularReview.id == review_id, TabularReview.user_id == user_id))
            .first()
        )
        if not review:
            raise ValueError(f"Tabular review {review_id} not found or access denied")
        return review

    def format_column_schema(self, columns: List[Dict[str, Any]]) -> str:
        if not columns:
            return "(колонок нет)"
        lines: List[str] = []
        for idx, col in enumerate(columns, 1):
            prompt = (col.get("prompt") or "").strip().replace("\n", " ")
            if len(prompt) > 240:
                prompt = prompt[:237] + "…"
            lines.append(
                f"{idx}. «{col.get('column_label', '')}» "
                f"[тип: {col.get('column_type', 'text')}] — вопрос колонки: {prompt or '—'}"
            )
        return "\n".join(lines)

    def format_table_data_for_llm(self, table_data: Dict[str, Any]) -> str:
        """Structured table context for LLM (rows × columns with types and statuses)."""
        review = table_data.get("review") or {}
        columns = table_data.get("columns") or []
        rows = table_data.get("rows") or []

        parts = [
            f"Название таблицы: {review.get('name') or '—'}",
        ]
        if review.get("description"):
            parts.append(f"Описание: {review['description']}")
        parts.append(f"Документов (строк): {len(rows)}")
        parts.append(f"Колонок: {len(columns)}")
        parts.append("")
        parts.append("Схема колонок:")
        parts.append(self.format_column_schema(columns))
        parts.append("")
        parts.append("Данные по строкам (каждая строка = один документ):")

        if not rows:
            parts.append("(документов в таблице нет)")
            return "\n".join(parts)

        for row_idx, row in enumerate(rows, 1):
            file_name = row.get("file_name") or "—"
            file_id = row.get("file_id") or ""
            parts.append(f"\n[Строка {row_idx}] {file_name} (id: {file_id})")
            cells = row.get("cells") or {}
            for col in columns:
                cell = cells.get(col["id"], {})
                label = col.get("column_label", "")
                ctype = col.get("column_type", "text")
                display = format_cell_display(cell)
                parts.append(f"  • {label} ({ctype}): {display}")

        return "\n".join(parts)

    def get_chat_history(
        self,
        review_id: str,
        user_id: str,
        *,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        review = self._get_review_for_user(review_id, user_id)
        session_id = tabular_chat_session_id(review_id)
        max_items = limit or (_history_turn_limit() * 2 + 2)
        messages = self.history_service.get_session_history(
            review.case_id,
            session_id,
            limit=max_items,
        )
        out: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.role not in ("user", "assistant") or not (msg.content or "").strip():
                continue
            item: Dict[str, Any] = {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
            }
            if msg.role == "assistant" and msg.source_references:
                item["citations"] = msg.source_references
            out.append(item)
        return out

    def _build_llm_messages(
        self,
        table_text: str,
        schema_text: str,
        question: str,
        history: List[Dict[str, str]],
    ) -> List[Any]:
        readability = case_assistant_readability_base()
        system_prompt = f"""Ты — юрист-аналитик. Отвечаешь только по данным табличного обзора документов дела.

Правила:
1. Язык ответа — русский.
2. Источник истины — значения ячеек таблицы ниже. Не выдумывай факты.
3. «— (не заполнено)» / «— (пусто)» — ячейка не заполнена; «N/A» — в документе нет ответа на вопрос колонки.
4. Указывай конкретные документы (имена файлов) и значения из колонок.
5. Учитывай предыдущие реплики диалога при уточняющих вопросах («а из них?», «покажи только эти»).
6. Если данных недостаточно — скажи прямо.

{readability}

Схема колонок:
{schema_text}

Актуальные данные таблицы:
{table_text}"""

        messages: List[Any] = [SystemMessage(content=system_prompt)]

        turn_limit = _history_turn_limit() * 2
        for item in history[-turn_limit:]:
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))

        messages.append(HumanMessage(content=question))
        return messages

    @staticmethod
    def _extract_citations(answer: str, table_data: Dict[str, Any]) -> List[Dict[str, str]]:
        citations: List[Dict[str, str]] = []
        answer_lower = answer.lower()
        for row in table_data.get("rows", []):
            file_name = row.get("file_name") or ""
            if file_name and file_name.lower() in answer_lower:
                citations.append({"file": file_name, "file_id": row.get("file_id", "")})
        return citations

    def _prepare_analysis(
        self,
        review_id: str,
        question: str,
        user_id: str,
    ) -> tuple[TabularReview, Dict[str, Any], List[Any], str]:
        if not self.llm:
            raise ValueError("LLM not configured")

        review = self._get_review_for_user(review_id, user_id)
        table_data = self.tabular_service.get_table_data(review_id, user_id)
        table_text = self.format_table_data_for_llm(table_data)
        schema_text = self.format_column_schema(table_data.get("columns") or [])
        history = self.history_service.get_history_for_context(review.case_id, tabular_chat_session_id(review_id))
        messages = self._build_llm_messages(table_text, schema_text, question.strip(), history)
        return review, table_data, messages, question.strip()

    def _persist_turn(
        self,
        review: TabularReview,
        question: str,
        answer: str,
        citations: List[Dict[str, str]],
    ) -> None:
        session_id = tabular_chat_session_id(str(review.id))
        try:
            self.history_service.save_user_message(review.case_id, question, session_id)
            self.history_service.save_assistant_message(
                review.case_id,
                answer,
                session_id,
                source_references=citations or None,
            )
        except Exception as e:
            logger.warning("Failed to persist tabular chat history: %s", e)

    async def stream_analyze_table(
        self,
        review_id: str,
        question: str,
        user_id: str,
    ) -> AsyncIterator[TabularChatStreamEvent]:
        """Stream LLM tokens, then emit done with citations and table stats."""
        if not self.llm:
            yield {"type": "error", "message": "LLM not configured"}
            return

        try:
            review, table_data, messages, trimmed_question = self._prepare_analysis(
                review_id, question, user_id
            )
        except ValueError as e:
            yield {"type": "error", "message": str(e)}
            return

        parts: List[str] = []
        try:
            async for piece in async_iter_llm_text_chunks(self.llm, messages):
                parts.append(piece)
                yield {"type": "text_delta", "text": piece}
        except Exception as e:
            logger.error("Tabular chat stream failed: %s", e, exc_info=True)
            yield {"type": "error", "message": "Не удалось сгенерировать ответ"}
            return

        answer = "".join(parts).strip()
        citations = self._extract_citations(answer, table_data)
        table_stats = {
            "total_rows": len(table_data.get("rows", [])),
            "total_columns": len(table_data.get("columns", [])),
        }

        self._persist_turn(review, trimmed_question, answer, citations)

        yield {
            "type": "done",
            "answer": answer,
            "citations": citations,
            "table_stats": table_stats,
        }

    async def analyze_table(
        self,
        review_id: str,
        question: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Non-streaming fallback — buffers stream_analyze_table."""
        result: Dict[str, Any] = {}
        async for event in self.stream_analyze_table(review_id, question, user_id):
            if event["type"] == "error":
                raise ValueError(event.get("message") or "Tabular chat failed")
            if event["type"] == "done":
                result = {
                    "answer": event.get("answer", ""),
                    "citations": event.get("citations", []),
                    "table_stats": event.get("table_stats", {}),
                }
        if not result:
            raise ValueError("Empty tabular chat response")
        return result
