"""
Statement SQL pipeline: plan → execute (facts) → synthesize (LLM) → citations.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.services.chat.statement_sql_executor import execute_statement_sql_plan
from app.services.chat.statement_sql_planner import plan_statement_sql
from app.services.chat.statement_sql_synthesizer import synthesize_statement_sql_answer
from app.services.chat.conversation_turn_state import turn_state_from_sql_plan

logger = logging.getLogger(__name__)


def run_statement_sql_pipeline(
    db: Session,
    *,
    case_id: str,
    question: str,
    scope_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]] = None,
    sql_plan_hints: Optional[dict] = None,
    prior_turn_state: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """
    End-to-end SQL path for bank statements.

    User-visible ``response`` always comes from synthesis (or minimal fallback),
    never from executor templates.
    """
    if not db or not case_id or not (question or "").strip():
        return None
    if not scope_file_ids:
        return None

    plan_result = plan_statement_sql(
        db,
        case_id=case_id,
        question=question,
        scope_file_ids=list(scope_file_ids),
        attached_file_ids=attached_file_ids,
        sql_plan_hints=sql_plan_hints,
        prior_turn_state=prior_turn_state,
    )
    if plan_result.plan is None:
        logger.info(
            "[StatementSqlPipeline] no plan resolver=%s reason=%s",
            plan_result.resolver,
            plan_result.reason,
        )
        return None

    execution = execute_statement_sql_plan(
        db,
        case_id=case_id,
        plan=plan_result.plan,
        scope_file_ids=list(scope_file_ids),
        question=question,
    )
    if not execution.resolved or execution.facts is None:
        return None

    synthesis = synthesize_statement_sql_answer(
        question=question,
        plan=plan_result.plan,
        execution=execution,
    )
    if not synthesis.text.strip():
        return None

    execution.answer = synthesis.text

    if execution.facts.row_count == 0 and plan_result.plan.operation in {"list", "find"}:
        logger.info(
            "[StatementSqlPipeline] empty list/find rows — defer to RAG fallback case=%s",
            case_id,
        )
        return {
            "sql_attempted_empty": True,
            "statement_sql_meta": {
                "resolver": plan_result.resolver,
                "operation": plan_result.plan.operation,
                "row_count": 0,
                "file_id": str(plan_result.plan.statement_file_id or "").strip(),
                "date_from": plan_result.plan.date_from,
                "date_to": plan_result.plan.date_to,
                "on_date": plan_result.plan.on_date,
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
        "[StatementSqlPipeline] op=%s rows=%s answer_len=%s synthesized=%s",
        plan_result.plan.operation,
        len(execution.rows),
        len(synthesis.text),
        synthesis.via_llm,
    )
    file_id = str(plan_result.plan.statement_file_id or "").strip()
    outbound_turn_state = turn_state_from_sql_plan(
        plan=plan_result.plan,
        file_id=file_id,
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
            "operation": plan_result.plan.operation,
            "row_count": execution.facts.row_count,
            "synthesized": synthesis.via_llm,
            "file_id": file_id,
            "date_from": plan_result.plan.date_from,
            "date_to": plan_result.plan.date_to,
            "on_date": plan_result.plan.on_date,
        },
    }
