"""Chat over the current operations table scope for one bank statement."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, List, Literal, Optional, TypedDict

from sqlalchemy.orm import Session

from app.config import config
from app.models.case import Case
from app.schemas.operations import OperationsSessionUiState
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat.case_transaction_graph import build_transaction_citations
from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    operations_ui_scope_reset_needed,
)
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.statement_sql_executor import execute_statement_sql_plan_on_rows
from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline
from app.services.chat.statement_sql_planner import plan_statement_sql
from app.services.chat.statement_sql_synthesizer import synthesize_statement_sql_answer
from app.services.chat.statement_sql_value_grounding import refine_plan_with_rows
from app.services.chat.statement_table_agent import (
    run_statement_table_agent,
    statement_table_agent_enabled,
)
from app.services.chat.turn_context_evidence import load_prior_turn_evidence_from_turns
from app.services.chat.turn_execution_contract import resolve_turn_execution_contract
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.operations_chat_scope import OperationsChatScope, filter_operations_scope

logger = logging.getLogger(__name__)

_STREAM_CHUNK_SIZE = 80


def operations_chat_session_id(case_id: str, file_id: str) -> str:
    return f"operations:{case_id}:{file_id}"


class OperationsChatStreamEvent(TypedDict, total=False):
    type: Literal["text_delta", "done", "error"]
    text: str
    answer: str
    citations: List[Dict[str, str]]
    table_stats: Dict[str, int]
    message: str


class OperationsChatService:
    def __init__(self, db: Session):
        self.db = db
        self.history_service = ChatHistoryService(db)

    def _get_case_for_user(self, case_id: str, user_id: str) -> Case:
        case = (
            self.db.query(Case)
            .filter(Case.id == case_id, Case.user_id == user_id)
            .first()
        )
        if not case:
            raise ValueError("Дело не найдено")
        return case

    def get_chat_history(
        self,
        case_id: str,
        user_id: str,
        file_id: str,
    ) -> List[Dict[str, Any]]:
        self._get_case_for_user(case_id, user_id)
        session_id = operations_chat_session_id(case_id, file_id)
        messages = self.history_service.get_session_history(case_id, session_id)
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

    def _load_conversation_history(
        self,
        *,
        case_id: str,
        file_id: str,
    ) -> List[Dict[str, str]]:
        session_id = operations_chat_session_id(case_id, file_id)
        messages = self.history_service.get_history_for_context(case_id, session_id)
        max_turns = max(2, int(getattr(config, "OPERATIONS_CHAT_HISTORY_MAX_TURNS", 6) or 6))
        return messages[-(max_turns * 2) :]

    def _load_prior_turn_state(
        self,
        *,
        case_id: str,
        file_id: str,
    ) -> Optional[ConversationTurnState]:
        session_id = operations_chat_session_id(case_id, file_id)
        messages = self.history_service.get_session_history(case_id, session_id)
        for msg in reversed(messages):
            if msg.role != "assistant":
                continue
            evidence = msg.evidence if isinstance(msg.evidence, dict) else {}
            retrieval = (
                evidence.get("retrieval_metadata")
                if isinstance(evidence.get("retrieval_metadata"), dict)
                else {}
            )
            state = ConversationTurnState.from_dict(
                retrieval.get("turn_state") if isinstance(retrieval.get("turn_state"), dict) else None
            )
            if state is not None and state.domain == "statement_analytics":
                return state
        return None

    def _load_prior_turn_evidence(
        self,
        *,
        case_id: str,
        file_id: str,
    ):
        session_id = operations_chat_session_id(case_id, file_id)
        messages = self.history_service.get_session_history(case_id, session_id)
        turns = [
            SessionMessageTurn(
                message_id=str(getattr(msg, "id", "") or ""),
                role=str(getattr(msg, "role", "") or ""),
                content=str(getattr(msg, "content", "") or ""),
                evidence=getattr(msg, "evidence", None),
                created_at=getattr(msg, "created_at", None),
            )
            for msg in messages
        ]
        return load_prior_turn_evidence_from_turns(turns)

    def _load_scope(
        self,
        *,
        case_id: str,
        file_id: str,
        ui_state: OperationsSessionUiState,
    ) -> OperationsChatScope:
        max_rows = max(
            5000,
            int(getattr(config, "OPERATIONS_CHAT_SCOPE_MAX_ROWS", 20000) or 20000),
        )
        page = CaseFileTransactionService.query_page(
            self.db,
            case_id=case_id,
            file_id=file_id,
            limit=max_rows,
        )
        available = CaseFileTransactionService.list_available_files(self.db, case_id)
        file_labels = {item.file_id: item.filename for item in available}
        file_label = file_labels.get(file_id) or file_id
        return filter_operations_scope(
            rows=page.rows,
            file_id=file_id,
            file_label=file_label,
            row_search=ui_state.row_search,
            value_filters=ui_state.value_filters,
        )

    def _clarify_message(self, has_active_scope_filters: bool) -> str:
        suffix = (
            " по текущему отфильтрованному виду таблицы"
            if has_active_scope_filters
            else " по текущей выписке"
        )
        return (
            "Не получилось однозначно понять запрос."
            f" Уточните, что именно нужно{suffix}: количество, сумму, список операций или поиск конкретного платежа."
        )

    def _persist_turn(
        self,
        case_id: str,
        file_id: str,
        question: str,
        answer: str,
        citations: List[Dict[str, str]],
        turn_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        session_id = operations_chat_session_id(case_id, file_id)
        evidence = None
        if turn_state:
            evidence = {"retrieval_metadata": {"turn_state": turn_state}}
        try:
            self.history_service.save_user_message(case_id, question, session_id)
            self.history_service.save_assistant_message(
                case_id,
                answer,
                session_id,
                source_references=citations or None,
                evidence=evidence,
            )
        except Exception as exc:
            logger.warning("Failed to persist operations chat history: %s", exc)

    @staticmethod
    def _ui_citations(raw_citations: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_citations:
            file_id = str(item.get("file_id") or item.get("source_id") or "").strip()
            file_name = str(
                item.get("file")
                or item.get("filename")
                or item.get("file_name")
                or file_id
            ).strip()
            key = (file_id, file_name)
            if not file_id or not file_name or key in seen:
                continue
            seen.add(key)
            out.append({"file": file_name, "file_id": file_id})
        return out

    async def stream_analyze(
        self,
        case_id: str,
        user_id: str,
        question: str,
        file_id: str,
        ui_state: Optional[OperationsSessionUiState] = None,
    ) -> AsyncIterator[OperationsChatStreamEvent]:
        case = self._get_case_for_user(case_id, user_id)
        normalized_file_id = (file_id or "").strip()
        if not normalized_file_id:
            yield {"type": "error", "message": "Выберите выписку"}
            return

        trimmed_question = (question or "").strip()
        if not trimmed_question:
            yield {"type": "error", "message": "Введите вопрос"}
            return

        scope = self._load_scope(
            case_id=case_id,
            file_id=normalized_file_id,
            ui_state=ui_state or OperationsSessionUiState(),
        )
        if not scope.filtered_rows:
            answer = (
                "После применённых фильтров и поиска в таблице не осталось операций для анализа. "
                "Снимите часть ограничений или уточните вопрос."
            )
            for piece in _chunk_text(answer):
                yield {"type": "text_delta", "text": piece}
            self._persist_turn(str(case.id), normalized_file_id, trimmed_question, answer, [])
            yield {
                "type": "done",
                "answer": answer,
                "citations": [],
                "table_stats": {
                    "total_rows": scope.total_rows,
                    "filtered_rows": 0,
                    "returned_rows": 0,
                    "amount_sum_rub": 0,
                },
            }
            return

        prior_evidence = self._load_prior_turn_evidence(
            case_id=str(case.id),
            file_id=normalized_file_id,
        )
        ui_scope_reset = operations_ui_scope_reset_needed(
            scope_has_active_filters=scope.has_active_scope_filters,
            prior_evidence=prior_evidence,
        )
        if ui_scope_reset:
            logger.info(
                "[OperationsChat] UI scope expanded to full statement — resetting prior turn context"
            )
            prior_evidence = None

        turn_contract = resolve_turn_execution_contract(
            question=trimmed_question,
            turn_context=None,
            prior_evidence=prior_evidence,
        )
        prior_state = turn_contract.prior_turn_state
        conversation_history = (
            []
            if ui_scope_reset
            else self._load_conversation_history(
                case_id=str(case.id),
                file_id=normalized_file_id,
            )
        )
        effective_question = (turn_contract.effective_query or trimmed_question).strip() or trimmed_question
        sql_hints = dict(turn_contract.sql_plan_hints)
        sql_hints.setdefault("statement_file_id", normalized_file_id)

        answer = ""
        citations: List[Dict[str, str]] = []
        turn_state: Optional[Dict[str, Any]] = None
        returned_rows = 0

        if not scope.has_active_scope_filters:
            patch = run_statement_sql_pipeline(
                self.db,
                case_id=str(case.id),
                question=effective_question,
                scope_file_ids=[normalized_file_id],
                attached_file_ids=[normalized_file_id],
                sql_plan_hints=sql_hints,
                prior_turn_state=prior_state.to_dict() if prior_state else None,
                conversation_history=conversation_history,
            )
            if patch:
                answer = str(patch.get("response") or "").strip()
                citations = self._ui_citations(list(patch.get("citations") or []))
                turn_state = (
                    patch.get("outbound_turn_state")
                    if isinstance(patch.get("outbound_turn_state"), dict)
                    else None
                )
                returned_rows = len(citations)

        if not answer:
            if statement_table_agent_enabled():
                agent_patch = run_statement_table_agent(
                    self.db,
                    case_id=str(case.id),
                    question=effective_question,
                    file_id=normalized_file_id,
                    file_label=scope.file_label,
                    rows=scope.filtered_rows,
                    scope_note=scope.scope_note(),
                    sql_plan_hints=sql_hints,
                    conversation_history=conversation_history,
                )
                if agent_patch and str(agent_patch.get("response") or "").strip():
                    answer = str(agent_patch.get("response") or "").strip()
                    citations = self._ui_citations(list(agent_patch.get("citations") or []))
                    turn_state = (
                        agent_patch.get("outbound_turn_state")
                        if isinstance(agent_patch.get("outbound_turn_state"), dict)
                        else None
                    )
                    returned_rows = len(citations)
                    meta = agent_patch.get("statement_sql_meta")
                    if isinstance(meta, dict) and meta.get("row_count") is not None:
                        returned_rows = int(meta.get("row_count") or returned_rows)

        if not answer:
            plan_result = plan_statement_sql(
                self.db,
                case_id=str(case.id),
                question=effective_question,
                scope_file_ids=[normalized_file_id],
                attached_file_ids=[normalized_file_id],
                sql_plan_hints=sql_hints,
                prior_turn_state=prior_state.to_dict() if prior_state else None,
                conversation_history=conversation_history,
            )
            if plan_result.plan is None:
                answer = self._clarify_message(scope.has_active_scope_filters)
            else:
                plan = refine_plan_with_rows(
                    plan_result.plan,
                    question=effective_question,
                    rows=scope.filtered_rows,
                )
                execution = execute_statement_sql_plan_on_rows(
                    plan=plan,
                    rows=scope.filtered_rows,
                    file_id=normalized_file_id,
                    file_label=scope.file_label,
                    question=effective_question,
                    scope_note=scope.scope_note(),
                )
                synthesis = synthesize_statement_sql_answer(
                    question=effective_question,
                    plan=plan,
                    execution=execution,
                    conversation_history=conversation_history,
                )
                answer = synthesis.text.strip()
                citations = self._ui_citations(
                    build_transaction_citations(self.db, str(case.id), execution.rows[:20])
                )
                returned_rows = len(execution.rows)
                turn_state = ConversationTurnState(
                    domain="statement_analytics",
                    statement_file_id=normalized_file_id,
                    operation=plan.operation,
                    date_from=plan.date_from,
                    date_to=plan.date_to,
                    on_date=plan.on_date,
                    time_hint=plan.time_hint,
                    description_contains=plan.description_contains,
                    structured_data_plane="sql",
                    amount_semantics=plan.amount_semantics,
                    amount_compare=plan.amount_compare,
                    amount_min=plan.amount_min,
                    amount_max=plan.amount_max,
                    ui_scope_had_filters=scope.has_active_scope_filters,
                    topic_file_ids=(normalized_file_id,),
                ).to_dict()

        if turn_state is not None:
            turn_state = {
                **turn_state,
                "ui_scope_had_filters": scope.has_active_scope_filters,
            }

        if not answer:
            yield {"type": "error", "message": "Не удалось сформировать ответ"}
            return

        for piece in _chunk_text(answer):
            yield {"type": "text_delta", "text": piece}

        amount_sum = sum(
            (row.amount_rub for row in scope.filtered_rows if row.amount_rub is not None),
            Decimal("0"),
        )
        table_stats = {
            "total_rows": scope.total_rows,
            "filtered_rows": len(scope.filtered_rows),
            "returned_rows": returned_rows,
            "amount_sum_rub": int(amount_sum),
        }

        self._persist_turn(
            str(case.id),
            normalized_file_id,
            trimmed_question,
            answer,
            citations,
            turn_state=turn_state,
        )

        yield {
            "type": "done",
            "answer": answer,
            "citations": citations,
            "table_stats": table_stats,
        }


def _chunk_text(text: str) -> List[str]:
    content = (text or "").strip()
    if not content:
        return []
    return [content[i : i + _STREAM_CHUNK_SIZE] for i in range(0, len(content), _STREAM_CHUNK_SIZE)]
