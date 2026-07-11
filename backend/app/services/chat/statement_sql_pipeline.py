"""
Statement SQL pipeline: table agent (primary) → classic plan→execute→synthesize (fallback).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.services.chat.statement_sql_executor import execute_statement_sql_plan
from app.services.chat.statement_sql_planner import file_display_name, plan_statement_sql
from app.services.chat.statement_sql_synthesizer import synthesize_statement_sql_answer
from app.services.chat.statement_sql_value_grounding import refine_plan_with_db
from app.services.chat.conversation_turn_state import turn_state_from_sql_plan
from app.services.chat.statement_table_agent import (
    run_statement_table_agent,
    statement_table_agent_enabled,
)

logger = logging.getLogger(__name__)


def _run_classic_statement_sql_pipeline(
    db: Session,
    *,
    case_id: str,
    question: str,
    scope_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]] = None,
    sql_plan_hints: Optional[dict] = None,
    prior_turn_state: Optional[dict] = None,
    conversation_history: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Legacy single-shot planner path (fallback when table agent is off/fails)."""
    plan_result = plan_statement_sql(
        db,
        case_id=case_id,
        question=question,
        scope_file_ids=list(scope_file_ids),
        attached_file_ids=attached_file_ids,
        sql_plan_hints=sql_plan_hints,
        prior_turn_state=prior_turn_state,
        conversation_history=conversation_history,
    )
    if plan_result.plan is None:
        logger.info(
            "[StatementSqlPipeline] no plan resolver=%s reason=%s",
            plan_result.resolver,
            plan_result.reason,
        )
        return None

    plan = plan_result.plan
    file_id = str(plan.statement_file_id or "").strip()
    if not file_id and len(scope_file_ids) == 1:
        file_id = str(scope_file_ids[0]).strip()
    if file_id:
        plan = refine_plan_with_db(
            db,
            case_id=case_id,
            plan=plan,
            question=question,
            file_id=file_id,
        )

    execution = execute_statement_sql_plan(
        db,
        case_id=case_id,
        plan=plan,
        scope_file_ids=list(scope_file_ids),
        question=question,
    )
    if not execution.resolved or execution.facts is None:
        return None

    synthesis = synthesize_statement_sql_answer(
        question=question,
        plan=plan,
        execution=execution,
        conversation_history=conversation_history,
    )
    if not synthesis.text.strip():
        return None

    execution.answer = synthesis.text

    if execution.facts.row_count == 0 and plan.operation in {"list", "find"}:
        logger.info(
            "[StatementSqlPipeline] empty list/find rows — defer to RAG fallback case=%s",
            case_id,
        )
        return {
            "sql_attempted_empty": True,
            "statement_sql_meta": {
                "resolver": plan_result.resolver,
                "operation": plan.operation,
                "row_count": 0,
                "file_id": str(plan.statement_file_id or file_id or "").strip(),
                "date_from": plan.date_from,
                "date_to": plan.date_to,
                "on_date": plan.on_date,
            },
        }

    citations: List[Dict[str, Any]] = []
    if execution.rows:
        from app.services.chat.case_transaction_graph import build_transaction_citations

        citations = build_transaction_citations(
            db,
            case_id=case_id,
            rows=execution.rows[:20],
        )

    logger.info(
        "[StatementSqlPipeline] classic op=%s rows=%s answer_len=%s synthesized=%s",
        plan.operation,
        len(execution.rows),
        len(synthesis.text),
        synthesis.via_llm,
    )
    resolved_file_id = str(plan.statement_file_id or file_id or "").strip()
    outbound_turn_state = turn_state_from_sql_plan(
        plan=plan,
        file_id=resolved_file_id,
        plane="sql",
    ).to_dict()

    return {
        "transaction_agent_resolved": True,
        "response": synthesis.text,
        "messages": [AIMessage(content=synthesis.text)],
        "citations": citations,
        "outbound_turn_state": outbound_turn_state,
        "statement_sql_meta": {
            "resolver": plan_result.resolver,
            "operation": plan.operation,
            "row_count": execution.facts.row_count,
            "synthesized": synthesis.via_llm,
            "file_id": resolved_file_id,
            "date_from": plan.date_from,
            "date_to": plan.date_to,
            "on_date": plan.on_date,
            "description_contains": plan.description_contains,
        },
    }


def run_statement_sql_pipeline(
    db: Session,
    *,
    case_id: str,
    question: str,
    scope_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]] = None,
    sql_plan_hints: Optional[dict] = None,
    prior_turn_state: Optional[dict] = None,
    conversation_history: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    End-to-end SQL path for bank statements.

    Primary: tool-calling statement table agent (multi-step, self-correcting).
    Fallback: classic single-shot planner → executor → synthesizer.
    """
    if not db or not case_id or not (question or "").strip():
        return None
    if not scope_file_ids:
        return None

    # Prefer a single unambiguous file for the table agent.
    file_id = ""
    hints = sql_plan_hints or {}
    hint_file = str(hints.get("statement_file_id") or "").strip()
    if hint_file and hint_file in set(scope_file_ids):
        file_id = hint_file
    elif len(scope_file_ids) == 1:
        file_id = str(scope_file_ids[0]).strip()
    elif prior_turn_state and str(prior_turn_state.get("statement_file_id") or "").strip() in set(
        scope_file_ids
    ):
        file_id = str(prior_turn_state.get("statement_file_id") or "").strip()

    if statement_table_agent_enabled() and file_id:
        agent_patch = run_statement_table_agent(
            db,
            case_id=case_id,
            question=question,
            file_id=file_id,
            file_label=file_display_name(db, file_id),
            sql_plan_hints=sql_plan_hints,
            conversation_history=conversation_history,
        )
        if agent_patch:
            return agent_patch
        logger.info(
            "[StatementSqlPipeline] table agent miss — classic fallback case=%s file=%s",
            case_id,
            file_id,
        )

    return _run_classic_statement_sql_pipeline(
        db,
        case_id=case_id,
        question=question,
        scope_file_ids=scope_file_ids,
        attached_file_ids=attached_file_ids,
        sql_plan_hints=sql_plan_hints,
        prior_turn_state=prior_turn_state,
        conversation_history=conversation_history,
    )
