"""Shared types for bank-statement SQL planning and execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

StatementSqlOperation = Literal[
    "count",
    "sum",
    "list",
    "find",
]

StatementAmountSemantics = Literal["any", "credit", "debit", "net"]

StatementSqlResolver = Literal["llm", "disabled", "llm_failed", "low_confidence"]


class StatementSqlPlan(BaseModel):
    """Structured execution plan for one statement SQL turn."""

    operation: StatementSqlOperation = Field(
        description=(
            "count: сколько операций за период. "
            "sum: итоговая сумма операций за период. "
            "list: перечислить операции (с фильтрами). "
            "find: одна/несколько операций в конкретную дату или время."
        ),
    )
    on_date: str = Field(
        default="",
        description="Одна дата DD.MM.YYYY, если вопрос про конкретный день.",
    )
    date_from: str = Field(
        default="",
        description="Начало периода DD.MM.YYYY (включительно).",
    )
    date_to: str = Field(
        default="",
        description="Конец периода DD.MM.YYYY (включительно).",
    )
    time_hint: str = Field(
        default="",
        description="Время HH:MM или HH:MM:SS из вопроса (например 19:28).",
    )
    description_contains: str = Field(
        default="",
        description="Подстрока в описании/назначении платежа (контрагент, назначение). Не «списания/поступления».",
    )
    amount_semantics: StatementAmountSemantics = Field(
        default="any",
        description=(
            "Направление суммы: credit — поступления (amount > 0); "
            "debit — списания (amount < 0); net/any — все операции."
        ),
    )
    statement_file_id: str = Field(
        default="",
        description="file_id выписки из каталога; пусто = единственная в scope.",
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.85)
    rationale: str = Field(default="", max_length=400)

    @field_validator(
        "on_date",
        "date_from",
        "date_to",
        "time_hint",
        "description_contains",
        "statement_file_id",
        mode="before",
    )
    @classmethod
    def _strip_fields(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("amount_semantics", mode="before")
    @classmethod
    def _normalize_amount_semantics(cls, value: object) -> str:
        raw = str(value or "any").strip().lower()
        if raw in {"any", "credit", "debit", "net"}:
            return raw
        if raw in {"income", "incoming", "positive"}:
            return "credit"
        if raw in {"outgoing", "expense", "negative"}:
            return "debit"
        return "any"


@dataclass(frozen=True)
class StatementSqlPlanResult:
    plan: Optional[StatementSqlPlan]
    resolver: StatementSqlResolver
    reason: str
