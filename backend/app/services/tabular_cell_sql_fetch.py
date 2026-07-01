"""Fetch structured SQL context for a tabular cell (statement rows in DB)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_executor import execute_statement_sql_plan
from app.services.chat.statement_sql_facts import build_facts_evidence_block
from app.services.chat.statement_sql_planner import plan_statement_sql

logger = logging.getLogger(__name__)


@dataclass
class TabularCellSqlContext:
    ok: bool
    context_text: str = ""
    rows: List[CaseFileTransaction] = field(default_factory=list)
    reason: str = ""


def fetch_tabular_cell_sql_context(
    db: Session,
    *,
    case_id: str,
    file_id: str,
    question: str,
) -> TabularCellSqlContext:
    """Plan + execute statement SQL; return evidence block for cell extraction LLM."""
    scope = [str(file_id).strip()]
    q = (question or "").strip()
    if not db or not case_id or not scope[0] or not q:
        return TabularCellSqlContext(ok=False, reason="empty_scope")

    plan_result = plan_statement_sql(
        db,
        case_id=str(case_id),
        question=q,
        scope_file_ids=scope,
        attached_file_ids=scope,
    )
    if plan_result.plan is None:
        logger.info(
            "[TabularCellSql] no plan case=%s file=%s resolver=%s reason=%s",
            case_id,
            file_id,
            plan_result.resolver,
            plan_result.reason,
        )
        return TabularCellSqlContext(
            ok=False,
            reason=plan_result.reason or plan_result.resolver or "no_plan",
        )

    execution = execute_statement_sql_plan(
        db,
        case_id=str(case_id),
        plan=plan_result.plan,
        scope_file_ids=scope,
        question=q,
    )
    if not execution.resolved or execution.facts is None:
        return TabularCellSqlContext(ok=False, reason="execution_failed")

    context_text = build_facts_evidence_block(
        question=q,
        plan=plan_result.plan,
        facts=execution.facts,
    )
    return TabularCellSqlContext(
        ok=True,
        context_text=context_text,
        rows=list(execution.rows or []),
    )
