"""
Normalize StatementSqlPlan after LLM — enforce period vs single-day semantics.

LLM often sets on_date=first day of month together with a month range; that would
count only one day. This module applies deterministic invariants before execution.
"""
from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, Optional, Tuple

from app.services.case_file_transaction_service import parse_user_date
from app.services.chat.statement_sql_amount_semantics import (
    infer_amount_semantics,
    is_direction_description_noise,
)
from app.services.chat.statement_sql_models import StatementSqlPlan

logger = logging.getLogger(__name__)

PeriodKind = Literal["single_day", "date_range", "calendar_month", "unspecified"]

_DATE_DMY_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TIME_ONLY_RE = re.compile(r"\b\d{1,2}:\d{2}\b")

# (regex stem — matches nominative/genitive/prepositional etc., month number)
_MONTH_STEMS: Tuple[Tuple[str, int], ...] = (
    (r"январ", 1),
    (r"феврал", 2),
    (r"март", 3),
    (r"апрел", 4),
    (r"ма[йяе]", 5),  # май, мая, мае («в мае»)
    (r"июн", 6),
    (r"июл", 7),
    (r"август", 8),
    (r"сентябр", 9),
    (r"октябр", 10),
    (r"ноябр", 11),
    (r"декабр", 12),
)

_MONTH_ALT = "|".join(stem for stem, _ in _MONTH_STEMS)

_MONTH_ONLY_RE = re.compile(
    rf"(?:"
    rf"(?:в|за|по)\s+(?:{_MONTH_ALT})\w*"
    rf"|(?:{_MONTH_ALT})\w*\s+(?:20\d{{2}}|г\.?)"
    rf")",
    re.IGNORECASE,
)

_SPECIFIC_DAY_OF_MONTH_RE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\w*"
    rf"(?:\s+(20\d{{2}}))?",
    re.IGNORECASE,
)
_NAMED_RANGE_RE = re.compile(
    rf"\bс\s+(\d{{1,2}})\s+({_MONTH_ALT})\w*(?:\s+(20\d{{2}}))?\s+по\s+(\d{{1,2}})\s+({_MONTH_ALT})\w*(?:\s+(20\d{{2}}))?",
    re.IGNORECASE,
)
_NUMERIC_RANGE_RE = re.compile(
    r"\bс\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})\s+по\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
    re.IGNORECASE,
)
_WHOLE_SCOPE_RE = re.compile(
    r"(?:по\s+всей\s+выписк\w*|по\s+выписк\w+\s+целиком|вся\s+выписк\w*|всю\s+выписк\w*)",
    re.IGNORECASE,
)
_AMOUNT_TOKEN_RE = re.compile(
    r"(?P<num>\d[\d\s]*(?:[.,]\d+)?)\s*(?P<suffix>к|k|тыс\.?|т(?:ыс)?\.?\s*р(?:уб)?\.?|тр|руб(?:лей|ля|.)?)?",
    re.IGNORECASE,
)
_AMOUNT_BETWEEN_RE = re.compile(
    r"(?:от|между)\s+(?P<first>\d[\d\s]*(?:[.,]\d+)?\s*(?:к|k|тыс\.?|т(?:ыс)?\.?\s*р(?:уб)?\.?|тр|руб(?:лей|ля|.)?)?)\s+"
    r"(?:до|и)\s+"
    r"(?P<second>\d[\d\s]*(?:[.,]\d+)?\s*(?:к|k|тыс\.?|т(?:ыс)?\.?\s*р(?:уб)?\.?|тр|руб(?:лей|ля|.)?)?)",
    re.IGNORECASE,
)
_AMOUNT_GT_RE = re.compile(
    r"(?:больше|более|свыше|выше|от)\s+(?P<value>\d[\d\s]*(?:[.,]\d+)?\s*(?:к|k|тыс\.?|т(?:ыс)?\.?\s*р(?:уб)?\.?|тр|руб(?:лей|ля|.)?)?)",
    re.IGNORECASE,
)
_AMOUNT_LT_RE = re.compile(
    r"(?:меньше|менее|ниже|до)\s+(?P<value>\d[\d\s]*(?:[.,]\d+)?\s*(?:к|k|тыс\.?|т(?:ыс)?\.?\s*р(?:уб)?\.?|тр|руб(?:лей|ля|.)?)?)",
    re.IGNORECASE,
)
_TOP_N_RE = re.compile(r"\bтоп[-\s]?(\d{1,2})\b", re.IGNORECASE)
_LARGEST_ONE_RE = re.compile(
    r"(?:самая\s+крупн\w*|крупнейш\w+\s+операц\w*|наибольш\w+\s+операц\w*|одна\s+крупн\w*)",
    re.IGNORECASE,
)
_COUNT_WITH_DATES_RE = re.compile(
    r"(?:в\s+какие\s+даты|какие\s+даты|с\s+датами|и\s+даты|перечисл\w*\s+даты)",
    re.IGNORECASE,
)

_PERIOD_OPS = frozenset({"count", "sum", "list", "top", "group"})
_DAY_OPS = frozenset({"count", "sum", "list", "find", "top", "group"})


@dataclass(frozen=True)
class PeriodHint:
    kind: PeriodKind
    on_date: Optional[date] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


@dataclass(frozen=True)
class AmountHint:
    compare: str = "none"
    amount_min: str = ""
    amount_max: str = ""


def _month_stem_to_number(stem: str) -> Optional[int]:
    stem_l = (stem or "").lower()
    for pattern, num in _MONTH_STEMS:
        if re.search(pattern, stem_l, re.IGNORECASE):
            return num
    return None


def _format_dmy(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def _month_bounds(year: int, month: int) -> Tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _extract_year(question: str, *, fallback_year: Optional[int] = None) -> int:
    match = _YEAR_RE.search(question or "")
    if match:
        return int(match.group(1))
    if fallback_year is not None:
        return fallback_year
    return date.today().year


def infer_period_from_question(question: str) -> PeriodHint:
    """
    Deterministic period hints from the user question (Russian).

    Distinguishes «в мае» (whole month) from «1 мая» / «11.06.2026» (single day).
    """
    q = (question or "").strip()
    if not q:
        return PeriodHint(kind="unspecified")

    ql = q.lower()

    numeric_range = _NUMERIC_RANGE_RE.search(q)
    if numeric_range:
        left = parse_user_date(numeric_range.group(1))
        right = parse_user_date(numeric_range.group(2))
        if left and right:
            lo, hi = sorted((left, right))
            return PeriodHint(kind="date_range", date_from=lo, date_to=hi)

    named_range = _NAMED_RANGE_RE.search(q)
    if named_range:
        start_month = _month_stem_to_number(named_range.group(2))
        end_month = _month_stem_to_number(named_range.group(5))
        start_year = int(named_range.group(3)) if named_range.group(3) else _extract_year(q)
        end_year = int(named_range.group(6)) if named_range.group(6) else start_year
        if start_month and end_month:
            try:
                left = date(start_year, start_month, int(named_range.group(1)))
                right = date(end_year, end_month, int(named_range.group(4)))
                lo, hi = sorted((left, right))
                return PeriodHint(kind="date_range", date_from=lo, date_to=hi)
            except ValueError:
                pass

    for match in _DATE_DMY_RE.finditer(q):
        day, month, year_raw = int(match.group(1)), int(match.group(2)), match.group(3)
        year = int(year_raw) if len(year_raw) == 4 else 2000 + int(year_raw)
        try:
            on = date(year, month, day)
            return PeriodHint(kind="single_day", on_date=on)
        except ValueError:
            continue

    day_month = _SPECIFIC_DAY_OF_MONTH_RE.search(q)
    if day_month:
        day = int(day_month.group(1))
        month = _month_stem_to_number(day_month.group(2))
        year = int(day_month.group(3)) if day_month.group(3) else _extract_year(q)
        if month:
            try:
                on = date(year, month, day)
                return PeriodHint(kind="single_day", on_date=on)
            except ValueError:
                pass

    if _MONTH_ONLY_RE.search(ql) and not _SPECIFIC_DAY_OF_MONTH_RE.search(q):
        for pattern, month_num in _MONTH_STEMS:
            if re.search(rf"(?:^|\s|[^\w]){pattern}\w*", ql, re.IGNORECASE):
                year = _extract_year(q)
                d_from, d_to = _month_bounds(year, month_num)
                return PeriodHint(
                    kind="calendar_month",
                    date_from=d_from,
                    date_to=d_to,
                )

    return PeriodHint(kind="unspecified")


def clears_statement_period(question: str) -> bool:
    return bool(_WHOLE_SCOPE_RE.search((question or "").strip()))


def _parse_amount_token(raw: str) -> Optional[Decimal]:
    match = _AMOUNT_TOKEN_RE.search((raw or "").strip())
    if not match:
        return None
    num = match.group("num")
    suffix = (match.group("suffix") or "").strip().lower()
    normalized = num.replace(" ", "").replace(",", ".")
    try:
        value = Decimal(normalized)
    except InvalidOperation:
        return None
    if suffix in {"к", "k", "тыс", "тыс.", "тр", "т.р", "т р", "тыс р", "тыс. р", "т.р.", "тыс.руб", "руб", "руб.", "рублей", "рубля"}:
        if suffix.startswith(("к", "k", "тыс", "тр", "т")):
            value *= Decimal("1000")
    return value


def infer_amount_hint_from_question(question: str) -> AmountHint:
    q = (question or "").strip().lower()
    if not q:
        return AmountHint()

    between = _AMOUNT_BETWEEN_RE.search(q)
    if between:
        left = _parse_amount_token(between.group("first"))
        right = _parse_amount_token(between.group("second"))
        if left is not None and right is not None:
            lo, hi = sorted((left, right))
            return AmountHint(compare="between", amount_min=str(lo), amount_max=str(hi))

    gt = _AMOUNT_GT_RE.search(q)
    if gt:
        value = _parse_amount_token(gt.group("value"))
        if value is not None:
            return AmountHint(compare="gt", amount_min=str(value))

    lt = _AMOUNT_LT_RE.search(q)
    if lt:
        value = _parse_amount_token(lt.group("value"))
        if value is not None:
            return AmountHint(compare="lt", amount_max=str(value))

    return AmountHint()


def _parse_plan_dates(plan: StatementSqlPlan) -> Tuple[Optional[date], Optional[date], Optional[date]]:
    on_d = parse_user_date(plan.on_date) if plan.on_date.strip() else None
    d_from = parse_user_date(plan.date_from) if plan.date_from.strip() else None
    d_to = parse_user_date(plan.date_to) if plan.date_to.strip() else None
    return on_d, d_from, d_to


def _is_multi_day_range(d_from: Optional[date], d_to: Optional[date]) -> bool:
    if d_from is None or d_to is None:
        return False
    return d_to > d_from


def apply_sql_plan_hints(
    plan: StatementSqlPlan,
    hints: dict[str, str] | None,
) -> StatementSqlPlan:
    """
    Fill underspecified structural fields from turn hints.

    Amount thresholds (compare/min/max) are intentionally NOT filled here: the planner
    owns them from the current question + dialogue. Re-injecting prior thresholds made
    stale filters (e.g. >9999) stick to unrelated follow-up topics.
    """
    if not hints:
        return plan
    updates: dict = {}
    for key in (
        "operation",
        "date_from",
        "date_to",
        "on_date",
        "time_hint",
        "statement_file_id",
        "description_contains",
        "amount_semantics",
    ):
        hint_val = str((hints or {}).get(key) or "").strip()
        if not hint_val:
            continue
        current = str(getattr(plan, key, "") or "").strip()
        if key == "amount_semantics" and current.lower() in {"", "any", "net"}:
            current = ""
        if key == "operation" or not current:
            updates[key] = hint_val
    if not updates:
        return plan
    return plan.model_copy(update=updates)


def infer_result_limit_from_question(question: str, operation: str) -> str:
    """Structural N for top/group from the question text."""
    q = (question or "").strip()
    if not q:
        return ""
    if operation == "top" and _LARGEST_ONE_RE.search(q):
        return "1"
    match = _TOP_N_RE.search(q)
    if match and operation in {"top", "group"}:
        return match.group(1)
    return ""


def normalize_statement_sql_plan(plan: StatementSqlPlan, question: str) -> StatementSqlPlan:
    """
    Apply invariants so period queries do not collapse to the first day of range.

    Order:
    1. Question-level calendar month hint overrides ambiguous LLM dates.
    2. Multi-day range clears on_date unless question is explicitly single-day.
    3. find + time_hint keeps on_date when present.
    4. Structural upgrades: count+dates → list; top/group result_limit.
    """
    hint = infer_period_from_question(question)
    on_d, d_from, d_to = _parse_plan_dates(plan)
    op = plan.operation

    updates: dict = {}

    # «сколько и в какие даты» needs rows, not a bare count.
    if op == "count" and _COUNT_WITH_DATES_RE.search(question or ""):
        updates["operation"] = "list"
        op = "list"

    if hint.kind == "calendar_month" and op in _PERIOD_OPS:
        updates["date_from"] = _format_dmy(hint.date_from)  # type: ignore[arg-type]
        updates["date_to"] = _format_dmy(hint.date_to)  # type: ignore[arg-type]
        updates["on_date"] = ""
        on_d, d_from, d_to = hint.date_from, hint.date_from, hint.date_to

    elif hint.kind == "single_day" and op in _DAY_OPS:
        updates["on_date"] = _format_dmy(hint.on_date)  # type: ignore[arg-type]
        updates["date_from"] = ""
        updates["date_to"] = ""
        on_d = hint.on_date
        d_from, d_to = None, None

    elif hint.kind == "date_range" and op in _PERIOD_OPS:
        updates["date_from"] = _format_dmy(hint.date_from)  # type: ignore[arg-type]
        updates["date_to"] = _format_dmy(hint.date_to)  # type: ignore[arg-type]
        updates["on_date"] = ""
        on_d, d_from, d_to = None, hint.date_from, hint.date_to

    if op in _PERIOD_OPS:
        if _is_multi_day_range(d_from, d_to):
            if hint.kind != "single_day":
                updates["on_date"] = ""
        elif on_d and d_from and d_to and on_d == d_from and d_to > d_from:
            updates["on_date"] = ""

    amount_hint = infer_amount_hint_from_question(question)
    if amount_hint.compare != "none":
        if not str(plan.amount_compare or "").strip() or str(plan.amount_compare).strip().lower() == "none":
            updates["amount_compare"] = amount_hint.compare
        if amount_hint.amount_min and not str(plan.amount_min or "").strip():
            updates["amount_min"] = amount_hint.amount_min
        if amount_hint.amount_max and not str(plan.amount_max or "").strip():
            updates["amount_max"] = amount_hint.amount_max

    limit_hint = infer_result_limit_from_question(question, op)
    if limit_hint and not str(plan.result_limit or "").strip():
        updates["result_limit"] = limit_hint

    if op == "find" and plan.time_hint.strip() and on_d:
        updates.setdefault("date_from", "")
        updates.setdefault("date_to", "")

    if not updates:
        return apply_amount_semantics_normalization(plan, question)

    normalized = plan.model_copy(update=updates)
    normalized = apply_amount_semantics_normalization(normalized, question)
    logger.info(
        "[StatementSqlPlanNormalize] op=%s hint=%s on=%s from=%s to=%s limit=%s",
        normalized.operation,
        hint.kind,
        normalized.on_date or "—",
        normalized.date_from or "—",
        normalized.date_to or "—",
        normalized.result_limit or "—",
    )
    return normalized


def apply_amount_semantics_normalization(
    plan: StatementSqlPlan,
    question: str,
) -> StatementSqlPlan:
    """
    Map «поступления/списания» to amount sign filters; drop bogus description_contains.
    """
    updates: dict = {}
    inferred = infer_amount_semantics(question)
    sem = str(plan.amount_semantics or "any").strip().lower()

    if is_direction_description_noise(plan.description_contains):
        updates["description_contains"] = ""

    if sem == "any" and inferred != "any":
        updates["amount_semantics"] = inferred
    elif sem in {"credit", "debit"} and is_direction_description_noise(plan.description_contains):
        updates["description_contains"] = ""

    if not updates:
        return plan
    return plan.model_copy(update=updates)


def effective_query_dates(
    plan: StatementSqlPlan,
) -> Tuple[Optional[date], Optional[date], Optional[date]]:
    """
    Dates actually passed to CaseFileTransactionService.query.

    For aggregate period operations, on_date is never combined with a multi-day range.
    """
    on_d, d_from, d_to = _parse_plan_dates(plan)
    if plan.operation in _PERIOD_OPS and _is_multi_day_range(d_from, d_to):
        on_d = None
    return on_d, d_from, d_to
