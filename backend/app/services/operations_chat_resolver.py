"""
Operations chat: единый путь — ReAct (мысль → Python в песочнице → наблюдение).

Intent классифицируется только для логов и метаданных; ответ всегда через run_statement_react_agent.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.conversation_turn_state import ConversationTurnState
from app.services.chat.statement_react_agent import (
    react_agent_enabled,
    run_statement_react_agent,
)
from app.services.chat.statement_react_progress import emit_statement_react_progress
from app.services.chat.statement_table_turn_contract import (
    StatementTurnIntent,
    classify_statement_turn_intent,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[Dict[str, Any]], None]


def resolve_operations_chat(
    db: Session,
    *,
    case_id: str,
    question: str,
    file_id: str,
    file_label: str,
    rows: Sequence[CaseFileTransaction],
    scope_note: str,
    sql_hints: Dict[str, Any],
    prior_state: Optional[ConversationTurnState],
    conversation_history: List[Dict[str, str]],
    ui_scope_had_filters: bool,
    progress: Optional[ProgressCallback] = None,
) -> tuple[Optional[Dict[str, Any]], StatementTurnIntent]:
    del sql_hints, prior_state, ui_scope_had_filters  # ReAct использует scope rows + историю

    intent = classify_statement_turn_intent(question)
    logger.info(
        "[OperationsChat] react-only intent=%s case=%s file=%s",
        intent,
        case_id,
        file_id,
    )

    if not react_agent_enabled():
        logger.warning("[OperationsChat] ReAct disabled — no fallback resolver")
        return None, intent

    emit_statement_react_progress(
        progress,
        step_id="react",
        phase="react",
        label="ReAct-анализ выписки",
        detail="Мысль → Python → наблюдение",
        status="running",
    )
    patch = run_statement_react_agent(
        db,
        case_id=case_id,
        question=question,
        file_id=file_id,
        file_label=file_label,
        rows=list(rows),
        scope_note=scope_note,
        conversation_history=conversation_history,
        progress_callback=progress,
    )
    emit_statement_react_progress(
        progress,
        step_id="react",
        phase="react",
        label="ReAct-анализ выписки",
        status="completed",
    )
    return patch, intent
