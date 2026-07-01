"""
Structured facts from statement SQL execution — input for LLM synthesis only.

User-facing text is never assembled here; only aggregates and row samples.
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


@dataclass
class StatementSqlFacts:
    """Deterministic SQL result — no user-facing prose."""

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
    sample_rows: List[StatementSqlRowFact] = field(default_factory=list)

    def has_matches(self) -> bool:
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
    if plan.rationale.strip():
        lines.append(f"Пояснение планировщика: {plan.rationale.strip()[:300]}")

    include_rows = facts.operation in {"list", "find"} and facts.sample_rows
    if include_rows:
        lines.append("")
        lines.append(f"Операции для ответа ({len(facts.sample_rows)} строк):")
        for rf in facts.sample_rows:
            page = f", стр. {rf.page}" if rf.page else ""
            lines.append(
                f"- №{rf.row_number} | {rf.date_text} | {rf.amount_text} | {rf.description}{page}"
            )
    elif facts.row_count == 0:
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
    Last-resort user text when synthesis LLM is unavailable.

    Short prose only — never debug pipe format or raw row dumps for count/sum.
    """
    file_ref = facts.file_label or "выписке"
    period = facts.period_label or "указанный период"

    if facts.row_count == 0:
        return (
            f"По файлу «{file_ref}» за {period} операций по заданному условию не найдено."
        )

    op = facts.operation
    if op == "count":
        amount_part = ""
        if facts.amount_sum is not None:
            amount_part = f" Суммарный оборот по строкам: {_format_amount_rub(facts.amount_sum)}."
        return (
            f"По файлу «{file_ref}» за {period} — {facts.row_count} операций.{amount_part}"
        ).strip()

    if op == "sum":
        return (
            f"По файлу «{file_ref}» за {period} сумма операций составляет "
            f"{_format_amount_rub(facts.amount_sum)} ({facts.row_count} операций)."
        )

    if op in {"list", "find"} and facts.sample_rows:
        intro = (
            f"По файлу «{file_ref}» за {period} найдено {facts.row_count} операций"
        )
        if facts.truncated:
            intro += " (показаны не все)"
        intro += ":"
        items: List[str] = [intro]
        for rf in facts.sample_rows[:10]:
            items.append(
                f"• {rf.date_text} — {rf.amount_text} — {rf.description}"
            )
        if facts.row_count > len(facts.sample_rows[:10]):
            items.append(f"… и ещё {facts.row_count - min(10, len(facts.sample_rows))} операций.")
        return "\n".join(items)

    return (
        f"По файлу «{file_ref}» за {period} найдено {facts.row_count} операций."
    )
