"""
Deterministic execution of StatementSqlPlan against case_file_transactions.

Returns structured facts only — user-facing text is produced by statement_sql_synthesizer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat.statement_sql_amount_semantics import (
    amount_filter_bounds,
    amount_semantics_label,
)
from app.services.chat.statement_sql_facts import (
    StatementSqlFacts,
    filter_rows_by_time_hint,
    row_fact_from_db,
    sum_row_amounts,
)
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_normalize import normalize_statement_sql_plan
from app.services.chat.statement_sql_planner import file_display_name

logger = logging.getLogger(__name__)

_MAX_LIST_ROWS = 50


@dataclass
class StatementSqlExecutionResult:
    resolved: bool
    facts: Optional[StatementSqlFacts] = None
    rows: List[CaseFileTransaction] = field(default_factory=list)
    # Populated by pipeline after synthesis (not by executor).
    answer: str = ""


def _parse_plan_date(value: str) -> Optional[date]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        d, m, y = raw.split(".")
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None


def _period_label(plan: StatementSqlPlan) -> str:
    if plan.on_date:
        return f"дата {plan.on_date}"
    if plan.date_from and plan.date_to:
        return f"период {plan.date_from} — {plan.date_to}"
    if plan.date_from:
        return f"с {plan.date_from}"
    if plan.date_to:
        return f"до {plan.date_to}"
    return "весь период выписки"


def _resolve_statement_file_id(
    plan: StatementSqlPlan,
    scope_file_ids: Sequence[str],
) -> Optional[str]:
    if plan.statement_file_id and plan.statement_file_id in scope_file_ids:
        return plan.statement_file_id
    if len(scope_file_ids) == 1:
        return scope_file_ids[0]
    return None


def _build_facts(
    *,
    plan: StatementSqlPlan,
    file_id: str,
    file_label: str,
    rows: List[CaseFileTransaction],
    truncated: bool,
) -> StatementSqlFacts:
    amount_sum = sum_row_amounts(rows)
    sample_rows = [row_fact_from_db(r) for r in rows[:40]]
    sem_label = amount_semantics_label(plan.amount_semantics)
    return StatementSqlFacts(
        operation=plan.operation,
        file_label=file_label,
        file_id=file_id,
        period_label=_period_label(plan),
        row_count=len(rows),
        amount_sum=amount_sum,
        truncated=truncated,
        time_hint=plan.time_hint,
        description_filter=plan.description_contains,
        amount_semantics_label=sem_label,
        sample_rows=sample_rows,
    )


def execute_statement_sql_plan(
    db: Session,
    *,
    case_id: str,
    plan: StatementSqlPlan,
    scope_file_ids: Sequence[str],
    question: str = "",
) -> StatementSqlExecutionResult:
    """Run SQL filters; return structured facts (no user-facing prose)."""
    if not db or not case_id or plan is None:
        return StatementSqlExecutionResult(resolved=False)

    plan = normalize_statement_sql_plan(plan, question)
    file_id = _resolve_statement_file_id(plan, scope_file_ids)
    if not file_id:
        logger.info(
            "[StatementSqlExecutor] ambiguous file scope plan_file=%s scope=%s",
            plan.statement_file_id,
            list(scope_file_ids),
        )
        return StatementSqlExecutionResult(resolved=False)

    on_date = _parse_plan_date(plan.on_date)
    date_from = _parse_plan_date(plan.date_from)
    date_to = _parse_plan_date(plan.date_to)
    limit = _MAX_LIST_ROWS if plan.operation in {"list", "find"} else None
    min_amount, max_amount = amount_filter_bounds(plan.amount_semantics)

    rows = CaseFileTransactionService.query(
        db,
        case_id=case_id,
        file_id=file_id,
        on_date=on_date,
        date_from=date_from,
        date_to=date_to,
        description_contains=plan.description_contains or None,
        min_amount=min_amount,
        max_amount=max_amount,
        limit=limit,
    )
    if plan.time_hint.strip():
        rows = filter_rows_by_time_hint(rows, plan.time_hint)
    file_label = file_display_name(db, file_id)
    truncated = bool(limit and len(rows) >= limit)

    facts = _build_facts(
        plan=plan,
        file_id=file_id,
        file_label=file_label,
        rows=rows,
        truncated=truncated,
    )

    logger.info(
        "[StatementSqlExecutor] op=%s file=%s rows=%s truncated=%s",
        plan.operation,
        file_id,
        len(rows),
        truncated,
    )
    return StatementSqlExecutionResult(
        resolved=True,
        facts=facts,
        rows=rows,
    )
