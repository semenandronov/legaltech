"""
Domain tools for the statement table agent.

No free-form SQL. Tools call the same deterministic executor as the classic pipeline,
so numbers are always produced by CaseFileTransactionService / in-memory filters.
"""
from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional

from langchain_core.tools import tool

from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.chat.statement_sql_executor import (
    execute_statement_sql_plan,
    execute_statement_sql_plan_on_rows,
)
from app.services.chat.statement_sql_facts import build_facts_evidence_block
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_normalize import normalize_statement_sql_plan
from app.services.chat.statement_sql_value_grounding import (
    DbDescriptionMatchProbe,
    RowsDescriptionMatchProbe,
    refine_plan_with_db,
    refine_plan_with_rows,
)
from app.services.chat.statement_table_session import get_statement_table_session
from app.services.transaction_description_match import (
    any_field_description_token_match,
    description_token_match,
)

logger = logging.getLogger(__name__)

StatementToolOperation = Literal["count", "sum", "list", "find", "top", "group"]
AmountSemantics = Literal["any", "credit", "debit", "net"]
AmountCompare = Literal["none", "gt", "gte", "lt", "lte", "between"]
GroupOrder = Literal["abs_sum", "count"]


def _record_tool(name: str) -> None:
    session = get_statement_table_session()
    session.tool_calls.append(name)


def _sample_descriptions(limit: int = 8) -> List[str]:
    session = get_statement_table_session()
    rows = list(session.rows or [])
    if not rows and session.db is not None:
        page = CaseFileTransactionService.query_page(
            session.db,
            case_id=session.case_id,
            file_id=session.file_id,
            limit=limit,
            offset=0,
        )
        rows = list(page.rows)
    out: List[str] = []
    seen: set[str] = set()
    for row in rows[: max(limit * 3, limit)]:
        text = str(row.description or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:160])
        if len(out) >= limit:
            break
    return out


@tool
def inspect_statement() -> str:
    """
    Обзор текущей выписки: число операций, диапазон дат, примеры описаний.

    Вызови в начале, если не уверен в периоде или формате данных.
    Не возвращает полный список операций.
    """
    _record_tool("inspect_statement")
    session = get_statement_table_session()

    if session.uses_in_memory_rows:
        rows = list(session.rows or [])
        dates = [r.operation_date for r in rows if r.operation_date is not None]
        date_min = min(dates).strftime("%d.%m.%Y") if dates else "—"
        date_max = max(dates).strftime("%d.%m.%Y") if dates else "—"
        total = len(rows)
    else:
        assert session.db is not None
        page = CaseFileTransactionService.query_page(
            session.db,
            case_id=session.case_id,
            file_id=session.file_id,
            limit=1,
            offset=0,
        )
        total = int(page.total or 0)
        summaries = CaseFileTransactionService.list_available_files(session.db, session.case_id)
        match = next((s for s in summaries if s.file_id == session.file_id), None)
        date_min = match.date_min.strftime("%d.%m.%Y") if match and match.date_min else "—"
        date_max = match.date_max.strftime("%d.%m.%Y") if match and match.date_max else "—"

    samples = _sample_descriptions()
    payload = {
        "file_id": session.file_id,
        "file_label": session.file_label,
        "operation_count": total,
        "date_min": date_min,
        "date_max": date_max,
        "scope_note": session.scope_note or None,
        "sample_descriptions": samples,
        "hint": (
            "Для чисел и списков используй query_statement. "
            "Перед фильтром по контрагенту проверь probe_description."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def probe_description(token: str) -> str:
    """
    Проверь, сколько операций матчится по токену в описании (целое слово/код).

    Вызови ПЕРЕД query_statement с description_contains, если токен короткий
    или есть сомнение (например VK, ИП, Yandex).

    Args:
        token: фрагмент контрагента/назначения из вопроса пользователя
    """
    _record_tool("probe_description")
    session = get_statement_table_session()
    needle = (token or "").strip()
    if not needle:
        return json.dumps({"token": "", "match_count": 0, "ok": False, "reason": "empty_token"})

    if session.uses_in_memory_rows:
        probe = RowsDescriptionMatchProbe(rows=list(session.rows or []))
        count = probe.count(needle)
        examples: List[str] = []
        for row in list(session.rows or [])[:200]:
            haystacks = (
                str(row.description or ""),
                str(row.operation_datetime_text or ""),
                str(row.amount_raw or ""),
                str(row.row_columns or ""),
            )
            if any_field_description_token_match(haystacks, needle) or description_token_match(
                str(row.description or ""), needle
            ):
                text = str(row.description or "").strip()
                if text and text not in examples:
                    examples.append(text[:160])
                if len(examples) >= 5:
                    break
    else:
        assert session.db is not None
        probe = DbDescriptionMatchProbe(
            db=session.db,
            case_id=session.case_id,
            file_id=session.file_id,
        )
        count = probe.count(needle)
        page = CaseFileTransactionService.query_page(
            session.db,
            case_id=session.case_id,
            file_id=session.file_id,
            description_contains=needle,
            limit=5,
            offset=0,
        )
        examples = [str(r.description or "").strip()[:160] for r in page.rows if r.description]

    return json.dumps(
        {
            "token": needle,
            "match_count": int(count),
            "ok": count > 0,
            "examples": examples,
            "hint": (
                "Если match_count=0 — не используй этот token в description_contains; "
                "уточни токен или спроси без фильтра по описанию."
                if count == 0
                else "Можно передавать token в query_statement.description_contains."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def run_statement_query(
    *,
    record_as: str,
    operation: StatementToolOperation,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
    time_hint: str = "",
    description_contains: str = "",
    amount_semantics: AmountSemantics = "any",
    amount_compare: AmountCompare = "none",
    amount_min: str = "",
    amount_max: str = "",
    result_limit: str = "",
    group_order: GroupOrder = "abs_sum",
    group_min_count: str = "",
) -> str:
    """Structured query executor shared by legacy and lawyer toolkit tools."""
    _record_tool(record_as)
    session = get_statement_table_session()
    question = (session.question or "").strip() or (
        f"op={operation} on={on_date} from={date_from} to={date_to} "
        f"desc={description_contains} sem={amount_semantics}"
    )

    plan = StatementSqlPlan(
        operation=operation,
        on_date=on_date or "",
        date_from=date_from or "",
        date_to=date_to or "",
        time_hint=time_hint or "",
        description_contains=description_contains or "",
        amount_semantics=amount_semantics or "any",
        amount_compare=amount_compare or "none",
        amount_min=amount_min or "",
        amount_max=amount_max or "",
        result_limit=result_limit or "",
        group_order=group_order or "abs_sum",
        group_min_count=group_min_count or "",
        statement_file_id=session.file_id,
        confidence=1.0,
        rationale="statement_table_agent",
    )
    plan = normalize_statement_sql_plan(plan, question)

    if session.uses_in_memory_rows:
        plan = refine_plan_with_rows(
            plan,
            question=question,
            rows=list(session.rows or []),
        )
        execution = execute_statement_sql_plan_on_rows(
            plan=plan,
            rows=list(session.rows or []),
            file_id=session.file_id,
            file_label=session.file_label,
            question=question,
            scope_note=session.scope_note,
        )
    else:
        assert session.db is not None
        plan = refine_plan_with_db(
            session.db,
            case_id=session.case_id,
            plan=plan,
            question=question,
            file_id=session.file_id,
        )
        execution = execute_statement_sql_plan(
            session.db,
            case_id=session.case_id,
            plan=plan,
            scope_file_ids=[session.file_id],
            question=question,
        )

    if not execution.resolved or execution.facts is None:
        return json.dumps(
            {"ok": False, "error": "query_failed", "operation": operation},
            ensure_ascii=False,
        )

    session.last_plan = plan
    session.last_facts = execution.facts
    session.last_execution = execution
    if execution.rows:
        seen = {r.id for r in session.citation_rows}
        for row in execution.rows:
            if row.id not in seen:
                session.citation_rows.append(row)
                seen.add(row.id)

    evidence = build_facts_evidence_block(
        question=question,
        plan=plan,
        facts=execution.facts,
    )
    logger.info(
        "[StatementTableTools] query op=%s rows=%s tools=%s",
        plan.operation,
        execution.facts.row_count,
        session.tool_calls,
    )
    return evidence


@tool
def query_statement(
    operation: StatementToolOperation,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
    time_hint: str = "",
    description_contains: str = "",
    amount_semantics: AmountSemantics = "any",
    amount_compare: AmountCompare = "none",
    amount_min: str = "",
    amount_max: str = "",
    result_limit: str = "",
    group_order: GroupOrder = "abs_sum",
    group_min_count: str = "",
) -> str:
    """
    Выполни аналитический запрос к таблице операций текущей выписки.

    operation:
      - count: только количество
      - sum: итоговая сумма
      - list: список (+ «сколько и в какие даты»)
      - find: поиск по дню/времени
      - top: крупнейшие по |сумме| (result_limit, для «самая крупная» = 1)
      - group: контрагенты / повторяющиеся (group_order=abs_sum|count; для повторяющихся group_min_count=2)

    Даты только DD.MM.YYYY. amount_semantics: credit=поступления, debit=списания.
    amount_compare фильтрует по |сумме|. Не выдумывай фильтры, которых нет в вопросе.

    Args:
        operation: тип аналитики
        on_date: один день DD.MM.YYYY
        date_from: начало периода
        date_to: конец периода
        time_hint: время HH:MM из вопроса
        description_contains: токен контрагента/назначения (после probe_description)
        amount_semantics: направление суммы
        amount_compare: порог по |сумме|
        amount_min: нижняя граница |суммы|
        amount_max: верхняя граница |суммы|
        result_limit: N для top/group
        group_order: сортировка групп
        group_min_count: минимум операций в группе
    """
    return run_statement_query(
        record_as="query_statement",
        operation=operation,
        on_date=on_date,
        date_from=date_from,
        date_to=date_to,
        time_hint=time_hint,
        description_contains=description_contains,
        amount_semantics=amount_semantics,
        amount_compare=amount_compare,
        amount_min=amount_min,
        amount_max=amount_max,
        result_limit=result_limit,
        group_order=group_order,
        group_min_count=group_min_count,
    )


def build_statement_table_tools() -> list:
    """Tool list for create_agent (bound via ContextVar session)."""
    return [inspect_statement, probe_description, query_statement]
