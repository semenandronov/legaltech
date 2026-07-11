"""
Structured facts from statement SQL execution — input for LLM synthesis only.

User-facing text for aggregate ops is composed deterministically here;
list/find may still go through the synthesizer LLM with these facts as the sole source of numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Optional, Sequence

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_models import StatementSqlPlan


@dataclass(frozen=True)
class StatementSqlRowFact:
    """One transaction row for synthesis (human-readable fields only)."""

    row_number: int
    date_text: str
    amount_text: str
    description: str
    page: Optional[int] = None


@dataclass(frozen=True)
class StatementSqlGroupFact:
    """One description-group aggregate for counterparties / recurring payments."""

    description: str
    op_count: int
    amount_sum_text: str
    abs_amount_sum_text: str


@dataclass
class StatementSqlFacts:
    """Deterministic SQL result — no user-facing prose in the structure itself."""

    operation: str
    file_label: str
    file_id: str
    period_label: str
    row_count: int
    amount_sum: Optional[Decimal] = None
    truncated: bool = False
    time_hint: str = ""
    description_filter: str = ""
    amount_semantics_label: str = ""
    amount_filter_label: str = ""
    scope_note: str = ""
    result_limit: int = 0
    sample_rows: List[StatementSqlRowFact] = field(default_factory=list)
    group_rows: List[StatementSqlGroupFact] = field(default_factory=list)

    def has_matches(self) -> bool:
        if self.operation == "group":
            return bool(self.group_rows)
        return self.row_count > 0


def _format_amount_rub(value: Decimal | float | None) -> str:
    if value is None:
        return "—"
    try:
        dec = Decimal(str(value))
        formatted = f"{dec:,.2f}".replace(",", " ").replace(".", ",")
        return f"{formatted} ₽"
    except Exception:
        return str(value)


def filter_rows_by_time_hint(
    rows: Sequence[CaseFileTransaction],
    time_hint: str,
) -> List[CaseFileTransaction]:
    """Narrow day-level rows to operations matching HH:MM from the question."""
    hint = (time_hint or "").strip()
    if not hint or not rows:
        return list(rows)
    needle = hint[:5] if len(hint) >= 5 else hint
    matched = [
        row
        for row in rows
        if needle in str(row.operation_datetime_text or "")
    ]
    return matched


def sum_row_amounts(rows: Sequence[CaseFileTransaction]) -> Optional[Decimal]:
    if not rows:
        return None
    return sum((r.amount_rub for r in rows if r.amount_rub is not None), Decimal("0"))


def row_fact_from_db(row: CaseFileTransaction) -> StatementSqlRowFact:
    return StatementSqlRowFact(
        row_number=int(row.global_row_index) + 1,
        date_text=str(row.operation_datetime_text or row.operation_date or "—"),
        amount_text=str(row.amount_raw or row.amount_rub or "—"),
        description=str(row.description or "—").strip(),
        page=int(row.page_start) if row.page_start else None,
    )


def group_fact_from_aggregate(
    *,
    description: str,
    op_count: int,
    amount_sum: Decimal,
    abs_amount_sum: Decimal,
) -> StatementSqlGroupFact:
    return StatementSqlGroupFact(
        description=(description or "—").strip() or "—",
        op_count=int(op_count),
        amount_sum_text=_format_amount_rub(amount_sum),
        abs_amount_sum_text=_format_amount_rub(abs_amount_sum),
    )


def build_facts_evidence_block(
    *,
    question: str,
    plan: StatementSqlPlan,
    facts: StatementSqlFacts,
) -> str:
    """Structured evidence for the synthesis LLM (not shown to the user)."""
    lines: List[str] = [
        f"Вопрос пользователя: {question.strip()}",
        f"Тип запроса (operation): {facts.operation}",
        f"Файл выписки: {facts.file_label or facts.file_id}",
        f"Период: {facts.period_label}",
        f"Количество операций по фильтру: {facts.row_count}",
    ]
    if facts.amount_sum is not None:
        lines.append(f"Сумма по строкам (алгебраическая): {_format_amount_rub(facts.amount_sum)}")
    if facts.truncated:
        lines.append(
            "Внимание: выборка обрезана лимитом запроса; в ответе укажи, что список может быть неполным."
        )
    if facts.time_hint.strip():
        lines.append(f"Фильтр по времени: {facts.time_hint.strip()}")
    if facts.description_filter.strip():
        lines.append(f"Фильтр по описанию: {facts.description_filter.strip()}")
    if facts.amount_semantics_label.strip():
        lines.append(f"Направление суммы: {facts.amount_semantics_label.strip()}")
    if facts.amount_filter_label.strip():
        lines.append(f"Фильтр по величине суммы: {facts.amount_filter_label.strip()}")
    if facts.scope_note.strip():
        lines.append(f"Область анализа: {facts.scope_note.strip()}")
    if facts.result_limit > 0:
        lines.append(f"Лимит результата: {facts.result_limit}")
    if plan.rationale.strip():
        lines.append(f"Пояснение планировщика: {plan.rationale.strip()[:300]}")

    if facts.operation in {"list", "find", "top"} and facts.sample_rows:
        label = {
            "list": "Операции для ответа",
            "find": "Операции для ответа",
            "top": "Крупнейшие операции по |сумме|",
        }[facts.operation]
        lines.append("")
        lines.append(f"{label} ({len(facts.sample_rows)} строк):")
        for rf in facts.sample_rows:
            page = f", стр. {rf.page}" if rf.page else ""
            lines.append(
                f"- №{rf.row_number} | {rf.date_text} | {rf.amount_text} | {rf.description}{page}"
            )
    elif facts.operation == "group" and facts.group_rows:
        lines.append("")
        lines.append(f"Группы по описанию ({len(facts.group_rows)}):")
        for gf in facts.group_rows:
            lines.append(
                f"- {gf.description} | операций: {gf.op_count} | "
                f"оборот |сумма|: {gf.abs_amount_sum_text} | алгебраическая сумма: {gf.amount_sum_text}"
            )
    elif facts.row_count == 0 and not facts.group_rows:
        lines.append("")
        lines.append("Операций по фильтру не найдено.")

    return "\n".join(lines)


def compose_fallback_answer(
    *,
    question: str,
    plan: StatementSqlPlan,
    facts: StatementSqlFacts,
) -> str:
    """
    Deterministic user text for aggregate ops and LLM-unavailable fallback.

    Short prose only — never debug pipe format or invented numbers.
    """
    del question  # facts already encode the answered slice
    file_ref = facts.file_label or "выписке"
    period = facts.period_label or "указанный период"
    scope_prefix = f"{facts.scope_note.strip()} " if facts.scope_note.strip() else ""

    if facts.operation == "group":
        if not facts.group_rows:
            return (
                f"{scope_prefix}По файлу «{file_ref}» за {period} групп по описанию не найдено."
            )
        intro = (
            f"{scope_prefix}По файлу «{file_ref}» за {period} — основные группы "
            f"по описанию (топ-{len(facts.group_rows)}):"
        )
        items: List[str] = [intro]
        for idx, gf in enumerate(facts.group_rows, start=1):
            items.append(
                f"{idx}. {gf.description} — {gf.op_count} оп., "
                f"оборот {gf.abs_amount_sum_text} (алг. {gf.amount_sum_text})"
            )
        return "\n".join(items)

    if facts.row_count == 0:
        return (
            f"{scope_prefix}По файлу «{file_ref}» за {period} операций по заданному условию не найдено."
        )

    op = facts.operation
    if op == "count":
        amount_part = ""
        if facts.amount_sum is not None:
            amount_part = f" Суммарный оборот по строкам: {_format_amount_rub(facts.amount_sum)}."
        return (
            f"{scope_prefix}По файлу «{file_ref}» за {period} — {facts.row_count} операций.{amount_part}"
        ).strip()

    if op == "sum":
        return (
            f"{scope_prefix}По файлу «{file_ref}» за {period} сумма операций составляет "
            f"{_format_amount_rub(facts.amount_sum)} ({facts.row_count} операций)."
        )

    if op == "top" and facts.sample_rows:
        n = len(facts.sample_rows)
        title = "Самая крупная операция" if n == 1 else f"Топ-{n} операций по |сумме|"
        intro = f"{scope_prefix}По файлу «{file_ref}» за {period} — {title}:"
        items = [intro]
        for idx, rf in enumerate(facts.sample_rows, start=1):
            items.append(
                f"{idx}. {rf.date_text} — {rf.amount_text} — {rf.description}"
            )
        return "\n".join(items)

    if op in {"list", "find"} and facts.sample_rows:
        intro = (
            f"{scope_prefix}По файлу «{file_ref}» за {period} найдено {facts.row_count} операций"
        )
        if facts.truncated:
            intro += f" (показаны первые {len(facts.sample_rows)})"
        intro += ":"
        items = [intro]
        for rf in facts.sample_rows:
            items.append(
                f"• {rf.date_text} — {rf.amount_text} — {rf.description}"
            )
        return "\n".join(items)

    return (
        f"{scope_prefix}По файлу «{file_ref}» за {period} найдено {facts.row_count} операций."
    )
