"""
Deterministic execution of StatementSqlPlan against case_file_transactions.

Returns structured facts only — user-facing text is produced by statement_sql_synthesizer
(or deterministic compose for aggregate ops).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    DescriptionGroupOrderBy,
    TransactionDescriptionGroup,
)
from app.services.operations_chat_scope import apply_plan_filters_to_rows
from app.services.chat.statement_sql_amount_semantics import (
    amount_filter_bounds,
    amount_semantics_label,
)
from app.services.transaction_amount_sign import effective_amount_rub
from app.services.chat.statement_sql_facts import (
    StatementSqlFacts,
    filter_rows_by_time_hint,
    group_fact_from_aggregate,
    row_fact_from_db,
    sum_row_amounts,
)
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_normalize import normalize_statement_sql_plan
from app.services.chat.statement_sql_planner import file_display_name
from app.services.transaction_amount_sign import effective_amount_rub

logger = logging.getLogger(__name__)

_MAX_LIST_ROWS = 50
_ROW_OPS = frozenset({"list", "find", "top"})
_AGGREGATE_OPS = frozenset({"count", "sum"})


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


def _parse_decimal_text(value: str) -> Optional[Decimal]:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except Exception:
        return None


def _amount_filter_label(plan: StatementSqlPlan) -> str:
    compare = (plan.amount_compare or "none").strip().lower()
    if compare == "none":
        return ""
    amount_min = _parse_decimal_text(plan.amount_min or "")
    amount_max = _parse_decimal_text(plan.amount_max or "")
    if compare == "gt" and amount_min is not None:
        return f"|сумма| > {amount_min}"
    if compare == "gte" and amount_min is not None:
        return f"|сумма| >= {amount_min}"
    if compare == "lt" and amount_max is not None:
        return f"|сумма| < {amount_max}"
    if compare == "lte" and amount_max is not None:
        return f"|сумма| <= {amount_max}"
    if compare == "between" and amount_min is not None and amount_max is not None:
        return f"{amount_min} <= |сумма| <= {amount_max}"
    return ""


def _row_amount(row: CaseFileTransaction) -> Optional[Decimal]:
    return effective_amount_rub(
        row.amount_rub,
        amount_raw=row.amount_raw,
        flow_direction=getattr(row, "flow_direction", None),
    )


def _matches_amount_compare(row: CaseFileTransaction, plan: StatementSqlPlan) -> bool:
    compare = (plan.amount_compare or "none").strip().lower()
    if compare == "none":
        return True
    amount = _row_amount(row)
    if amount is None:
        return False
    value = abs(amount)
    amount_min = _parse_decimal_text(plan.amount_min or "")
    amount_max = _parse_decimal_text(plan.amount_max or "")
    if compare == "gt":
        return amount_min is not None and value > amount_min
    if compare == "gte":
        return amount_min is not None and value >= amount_min
    if compare == "lt":
        return amount_max is not None and value < amount_max
    if compare == "lte":
        return amount_max is not None and value <= amount_max
    if compare == "between":
        return amount_min is not None and amount_max is not None and amount_min <= value <= amount_max
    return True


def _apply_amount_compare(
    rows: Sequence[CaseFileTransaction],
    plan: StatementSqlPlan,
) -> List[CaseFileTransaction]:
    compare = (plan.amount_compare or "none").strip().lower()
    if compare == "none":
        return list(rows)
    return [row for row in rows if _matches_amount_compare(row, plan)]


def _plan_abs_amount_filters(
    plan: StatementSqlPlan,
) -> tuple[str, Optional[Decimal], Optional[Decimal]]:
    compare = (plan.amount_compare or "none").strip().lower()
    if compare not in {"gt", "gte", "lt", "lte", "between"}:
        return "none", None, None
    return compare, _parse_decimal_text(plan.amount_min or ""), _parse_decimal_text(plan.amount_max or "")


def _resolve_statement_file_id(
    plan: StatementSqlPlan,
    scope_file_ids: Sequence[str],
) -> Optional[str]:
    if plan.statement_file_id and plan.statement_file_id in scope_file_ids:
        return plan.statement_file_id
    if len(scope_file_ids) == 1:
        return scope_file_ids[0]
    return None


def _group_order_for_plan(plan: StatementSqlPlan) -> DescriptionGroupOrderBy:
    if (plan.group_order or "abs_sum").strip().lower() == "count":
        return "count_desc"
    return "abs_sum_desc"


def _sort_rows_by_abs_amount(rows: Sequence[CaseFileTransaction]) -> List[CaseFileTransaction]:
    return sorted(
        rows,
        key=lambda r: (
            -(abs(a) if (a := _row_amount(r)) is not None else Decimal("0")),
            r.operation_date or date.max,
            int(r.global_row_index or 0),
        ),
    )


def _group_rows_in_memory(
    rows: Sequence[CaseFileTransaction],
    *,
    order_by: DescriptionGroupOrderBy,
    limit: int,
    min_op_count: int,
) -> List[TransactionDescriptionGroup]:
    buckets: dict[str, list[CaseFileTransaction]] = defaultdict(list)
    for row in rows:
        key = str(row.description or "").strip() or "—"
        buckets[key].append(row)

    groups: List[TransactionDescriptionGroup] = []
    for description, bucket in buckets.items():
        if len(bucket) < min_op_count:
            continue
        amounts = [_row_amount(r) for r in bucket]
        amount_sum = sum((a for a in amounts if a is not None), Decimal("0"))
        abs_amount_sum = sum((abs(a) for a in amounts if a is not None), Decimal("0"))
        groups.append(
            TransactionDescriptionGroup(
                description=description,
                op_count=len(bucket),
                amount_sum=amount_sum,
                abs_amount_sum=abs_amount_sum,
            )
        )

    if order_by == "count_desc":
        groups.sort(key=lambda g: (g.op_count, g.abs_amount_sum), reverse=True)
    else:
        groups.sort(key=lambda g: (g.abs_amount_sum, g.op_count), reverse=True)
    return groups[: max(1, limit)]


def _build_facts(
    *,
    plan: StatementSqlPlan,
    file_id: str,
    file_label: str,
    rows: List[CaseFileTransaction],
    truncated: bool,
    row_count: Optional[int] = None,
    amount_sum: Optional[Decimal] = None,
    scope_note: str = "",
    group_rows: Optional[List[TransactionDescriptionGroup]] = None,
) -> StatementSqlFacts:
    sample_rows = [row_fact_from_db(r) for r in rows]
    groups = group_rows or []
    group_facts = [
        group_fact_from_aggregate(
            description=g.description,
            op_count=g.op_count,
            amount_sum=g.amount_sum,
            abs_amount_sum=g.abs_amount_sum,
        )
        for g in groups
    ]
    resolved_count = row_count if row_count is not None else len(rows)
    if plan.operation == "group":
        resolved_count = sum(g.op_count for g in groups)
    resolved_sum = amount_sum if amount_sum is not None else sum_row_amounts(rows)
    sem_label = amount_semantics_label(plan.amount_semantics)
    result_limit = plan.resolved_result_limit() if plan.operation in {"top", "group"} else 0
    return StatementSqlFacts(
        operation=plan.operation,
        file_label=file_label,
        file_id=file_id,
        period_label=_period_label(plan),
        row_count=resolved_count,
        amount_sum=resolved_sum,
        truncated=truncated,
        time_hint=plan.time_hint,
        description_filter=plan.description_contains,
        amount_semantics_label=sem_label,
        amount_filter_label=_amount_filter_label(plan),
        scope_note=scope_note,
        result_limit=result_limit,
        sample_rows=sample_rows,
        group_rows=group_facts,
    )


def _common_filter_kwargs(plan: StatementSqlPlan, file_id: str) -> dict:
    on_date = _parse_plan_date(plan.on_date)
    date_from = _parse_plan_date(plan.date_from)
    date_to = _parse_plan_date(plan.date_to)
    min_amount, max_amount = amount_filter_bounds(plan.amount_semantics)
    abs_compare, abs_amount_min, abs_amount_max = _plan_abs_amount_filters(plan)
    return {
        "file_id": file_id,
        "on_date": on_date,
        "date_from": date_from,
        "date_to": date_to,
        "description_contains": plan.description_contains or None,
        "min_amount": min_amount,
        "max_amount": max_amount,
        "abs_amount_compare": abs_compare,
        "abs_amount_min": abs_amount_min,
        "abs_amount_max": abs_amount_max,
    }


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

    filters = _common_filter_kwargs(plan, file_id)
    file_label = file_display_name(db, file_id)
    time_hint = plan.time_hint.strip()
    op = plan.operation

    # Time-of-day filter requires row payloads; fall back to in-memory path.
    if time_hint and op in _AGGREGATE_OPS | _ROW_OPS | {"group"}:
        page = CaseFileTransactionService.query_page(
            db,
            case_id=case_id,
            **filters,
            order_by="date_asc",
            limit=10_000,
        )
        matched = filter_rows_by_time_hint(page.rows, time_hint)
        return _finalize_from_matched_rows(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            matched=matched,
            question=question,
        )

    if op in _AGGREGATE_OPS:
        totals = CaseFileTransactionService.aggregate_totals(db, case_id=case_id, **filters)
        facts = _build_facts(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            rows=[],
            truncated=False,
            row_count=totals.count,
            amount_sum=totals.amount_sum,
        )
        logger.info(
            "[StatementSqlExecutor] op=%s file=%s rows=%s truncated=False",
            op,
            file_id,
            totals.count,
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=[])

    if op == "group":
        limit = plan.resolved_result_limit()
        order_by = _group_order_for_plan(plan)
        min_op_count = plan.resolved_group_min_count()
        groups = CaseFileTransactionService.aggregate_by_description(
            db,
            case_id=case_id,
            **filters,
            order_by=order_by,
            limit=limit,
            min_op_count=min_op_count,
        )
        facts = _build_facts(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            rows=[],
            truncated=False,
            group_rows=groups,
        )
        logger.info(
            "[StatementSqlExecutor] op=group file=%s groups=%s",
            file_id,
            len(groups),
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=[])

    if op == "top":
        limit = plan.resolved_result_limit()
        page = CaseFileTransactionService.query_page(
            db,
            case_id=case_id,
            **filters,
            order_by="abs_amount_desc",
            limit=limit,
        )
        facts = _build_facts(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            rows=page.rows,
            truncated=False,
            row_count=len(page.rows),
            amount_sum=sum_row_amounts(page.rows),
        )
        logger.info(
            "[StatementSqlExecutor] op=top file=%s rows=%s limit=%s",
            file_id,
            len(page.rows),
            limit,
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=list(page.rows))

    # list / find — honest total via query_page
    page = CaseFileTransactionService.query_page(
        db,
        case_id=case_id,
        **filters,
        order_by="date_asc",
        limit=_MAX_LIST_ROWS,
    )
    truncated = page.total > len(page.rows)
    facts = _build_facts(
        plan=plan,
        file_id=file_id,
        file_label=file_label,
        rows=page.rows,
        truncated=truncated,
        row_count=page.total,
        amount_sum=None if truncated else sum_row_amounts(page.rows),
    )
    # For truncated lists, amount_sum over the page is misleading — leave None
    # unless we compute full aggregate (cheap and honest).
    if truncated:
        totals = CaseFileTransactionService.aggregate_totals(db, case_id=case_id, **filters)
        facts.amount_sum = totals.amount_sum
        facts.row_count = totals.count

    logger.info(
        "[StatementSqlExecutor] op=%s file=%s rows=%s truncated=%s",
        op,
        file_id,
        facts.row_count,
        facts.truncated,
    )
    return StatementSqlExecutionResult(
        resolved=True,
        facts=facts,
        rows=list(page.rows),
    )


def _finalize_from_matched_rows(
    *,
    plan: StatementSqlPlan,
    file_id: str,
    file_label: str,
    matched: List[CaseFileTransaction],
    question: str = "",
    scope_note: str = "",
) -> StatementSqlExecutionResult:
    """Shared post-filter path for DB time-hint and in-memory execution."""
    op = plan.operation

    if op in _AGGREGATE_OPS:
        facts = _build_facts(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            rows=[],
            truncated=False,
            row_count=len(matched),
            amount_sum=sum_row_amounts(matched),
            scope_note=scope_note,
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=[])

    if op == "group":
        groups = _group_rows_in_memory(
            matched,
            order_by=_group_order_for_plan(plan),
            limit=plan.resolved_result_limit(),
            min_op_count=plan.resolved_group_min_count(),
        )
        facts = _build_facts(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            rows=[],
            truncated=False,
            group_rows=groups,
            scope_note=scope_note,
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=[])

    if op == "top":
        limited = _sort_rows_by_abs_amount(matched)[: plan.resolved_result_limit()]
        facts = _build_facts(
            plan=plan,
            file_id=file_id,
            file_label=file_label,
            rows=limited,
            truncated=False,
            row_count=len(limited),
            amount_sum=sum_row_amounts(limited),
            scope_note=scope_note,
        )
        return StatementSqlExecutionResult(resolved=True, facts=facts, rows=limited)

    # list / find
    total_count = len(matched)
    limited_rows = matched[:_MAX_LIST_ROWS]
    truncated = total_count > len(limited_rows)
    facts = _build_facts(
        plan=plan,
        file_id=file_id,
        file_label=file_label,
        rows=limited_rows,
        truncated=truncated,
        row_count=total_count,
        amount_sum=sum_row_amounts(matched),
        scope_note=scope_note,
    )
    return StatementSqlExecutionResult(
        resolved=True,
        facts=facts,
        rows=limited_rows,
    )


def execute_statement_sql_plan_on_rows(
    *,
    plan: StatementSqlPlan,
    rows: Sequence[CaseFileTransaction],
    file_id: str,
    file_label: str,
    question: str = "",
    scope_note: str = "",
) -> StatementSqlExecutionResult:
    """Run the same SQL-plan semantics over a prefiltered in-memory row scope."""
    if plan is None or not file_id:
        return StatementSqlExecutionResult(resolved=False)

    plan = normalize_statement_sql_plan(plan, question)
    on_date = _parse_plan_date(plan.on_date)
    date_from = _parse_plan_date(plan.date_from)
    date_to = _parse_plan_date(plan.date_to)
    min_amount, max_amount = amount_filter_bounds(plan.amount_semantics)

    matched = apply_plan_filters_to_rows(
        rows,
        on_date=on_date,
        date_from=date_from,
        date_to=date_to,
        description_contains=plan.description_contains or "",
        min_amount=min_amount,
        max_amount=max_amount,
    )
    matched = _apply_amount_compare(matched, plan)
    if plan.time_hint.strip():
        matched = filter_rows_by_time_hint(matched, plan.time_hint)

    result = _finalize_from_matched_rows(
        plan=plan,
        file_id=file_id,
        file_label=file_label,
        matched=matched,
        question=question,
        scope_note=scope_note,
    )
    logger.info(
        "[StatementSqlExecutorRows] op=%s file=%s rows=%s truncated=%s",
        plan.operation,
        file_id,
        result.facts.row_count if result.facts else 0,
        result.facts.truncated if result.facts else False,
    )
    return result
