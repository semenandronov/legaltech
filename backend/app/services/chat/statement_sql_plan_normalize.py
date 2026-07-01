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


@dataclass(frozen=True)
class PeriodHint:
    kind: PeriodKind
    on_date: Optional[date] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None


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
    """Merge structured hints from turn execution contract (prior turn state)."""
    if not hints:
        return plan
    updates: dict = {}
    for key in ("operation", "date_from", "date_to", "on_date", "statement_file_id", "amount_semantics"):
        hint_val = str((hints or {}).get(key) or "").strip()
        if not hint_val:
            continue
        current = str(getattr(plan, key, "") or "").strip()
        if key == "operation" or not current:
            updates[key] = hint_val
    if not updates:
        return plan
    return plan.model_copy(update=updates)


def normalize_statement_sql_plan(plan: StatementSqlPlan, question: str) -> StatementSqlPlan:
    """
    Apply invariants so period queries do not collapse to the first day of range.

    Order:
    1. Question-level calendar month hint overrides ambiguous LLM dates.
    2. Multi-day range clears on_date unless question is explicitly single-day.
    3. find + time_hint keeps on_date when present.
    """
    hint = infer_period_from_question(question)
    on_d, d_from, d_to = _parse_plan_dates(plan)
    op = plan.operation

    updates: dict = {}

    if hint.kind == "calendar_month" and op in {"count", "sum", "list"}:
        updates["date_from"] = _format_dmy(hint.date_from)  # type: ignore[arg-type]
        updates["date_to"] = _format_dmy(hint.date_to)  # type: ignore[arg-type]
        updates["on_date"] = ""
        on_d, d_from, d_to = hint.date_from, hint.date_from, hint.date_to

    elif hint.kind == "single_day" and op in {"count", "sum", "list", "find"}:
        updates["on_date"] = _format_dmy(hint.on_date)  # type: ignore[arg-type]
        updates["date_from"] = ""
        updates["date_to"] = ""
        on_d = hint.on_date
        d_from, d_to = None, None

    if op in {"count", "sum", "list"}:
        if _is_multi_day_range(d_from, d_to):
            if hint.kind != "single_day":
                updates["on_date"] = ""
        elif on_d and d_from and d_to and on_d == d_from and d_to > d_from:
            updates["on_date"] = ""

    if op == "find" and plan.time_hint.strip() and on_d:
        updates.setdefault("date_from", "")
        updates.setdefault("date_to", "")

    if not updates:
        return apply_amount_semantics_normalization(plan, question)

    normalized = plan.model_copy(update=updates)
    normalized = apply_amount_semantics_normalization(normalized, question)
    logger.info(
        "[StatementSqlPlanNormalize] op=%s hint=%s on=%s from=%s to=%s",
        normalized.operation,
        hint.kind,
        normalized.on_date or "—",
        normalized.date_from or "—",
        normalized.date_to or "—",
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
    if plan.operation in {"count", "sum", "list"} and _is_multi_day_range(d_from, d_to):
        on_d = None
    return on_d, d_from, d_to
