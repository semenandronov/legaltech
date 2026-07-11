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
    "top",
    "group",
]

StatementAmountSemantics = Literal["any", "credit", "debit", "net"]
StatementAmountCompare = Literal["none", "gt", "gte", "lt", "lte", "between"]
StatementGroupOrder = Literal["abs_sum", "count"]

StatementSqlResolver = Literal["llm", "disabled", "llm_failed", "low_confidence"]

_DEFAULT_TOP_N = 5
_DEFAULT_GROUP_N = 10
_MAX_RESULT_LIMIT = 50


class StatementSqlPlan(BaseModel):
    """Structured execution plan for one statement SQL turn."""

    operation: StatementSqlOperation = Field(
        description=(
            "count: сколько операций за период. "
            "sum: итоговая сумма операций за период. "
            "list: перечислить операции (с фильтрами), в т.ч. «сколько и в какие даты». "
            "find: одна/несколько операций в конкретную дату или время. "
            "top: крупнейшие по |сумме| (топ-N / самая крупная). "
            "group: основные контрагенты / повторяющиеся платежи (группировка по описанию)."
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
        description="Токен в описании/назначении платежа (контрагент, назначение). Не «списания/поступления».",
    )
    amount_semantics: StatementAmountSemantics = Field(
        default="any",
        description=(
            "Направление суммы: credit — поступления (amount > 0); "
            "debit — списания (amount < 0); net/any — все операции."
        ),
    )
    amount_compare: StatementAmountCompare = Field(
        default="none",
        description=(
            "Фильтр по абсолютной величине суммы операции: "
            "gt/gte/lt/lte/between или none."
        ),
    )
    amount_min: str = Field(
        default="",
        description="Нижняя граница абсолютной суммы операции, например 10000.",
    )
    amount_max: str = Field(
        default="",
        description="Верхняя граница абсолютной суммы операции, например 50000.",
    )
    result_limit: str = Field(
        default="",
        description=(
            "Лимит строк результата для top/group (например 5 или 10). "
            "Пусто = default: top→5, group→10. Для «самая крупная» → 1."
        ),
    )
    group_order: StatementGroupOrder = Field(
        default="abs_sum",
        description=(
            "Только для group: abs_sum — основные контрагенты по |обороту|; "
            "count — повторяющиеся/частые платежи по числу операций."
        ),
    )
    group_min_count: str = Field(
        default="",
        description=(
            "Только для group: минимальное число операций в группе. "
            "Для «повторяющиеся» → 2; иначе пусто (=1)."
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
        "amount_min",
        "amount_max",
        "result_limit",
        "group_min_count",
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

    @field_validator("amount_compare", mode="before")
    @classmethod
    def _normalize_amount_compare(cls, value: object) -> str:
        raw = str(value or "none").strip().lower()
        aliases = {
            "greater_than": "gt",
            "more_than": "gt",
            ">": "gt",
            "greater_or_equal": "gte",
            ">=": "gte",
            "less_than": "lt",
            "<": "lt",
            "less_or_equal": "lte",
            "<=": "lte",
            "range": "between",
        }
        raw = aliases.get(raw, raw)
        if raw in {"none", "gt", "gte", "lt", "lte", "between"}:
            return raw
        return "none"

    @field_validator("group_order", mode="before")
    @classmethod
    def _normalize_group_order(cls, value: object) -> str:
        raw = str(value or "abs_sum").strip().lower()
        aliases = {
            "sum": "abs_sum",
            "abs": "abs_sum",
            "volume": "abs_sum",
            "frequency": "count",
            "freq": "count",
            "ops": "count",
        }
        raw = aliases.get(raw, raw)
        if raw in {"abs_sum", "count"}:
            return raw
        return "abs_sum"

    def resolved_result_limit(self) -> int:
        """Effective N for top/group (clamped)."""
        raw = (self.result_limit or "").strip()
        default = _DEFAULT_TOP_N if self.operation == "top" else _DEFAULT_GROUP_N
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(1, min(_MAX_RESULT_LIMIT, value))

    def resolved_group_min_count(self) -> int:
        raw = (self.group_min_count or "").strip()
        if not raw:
            return 1
        try:
            value = int(raw)
        except ValueError:
            return 1
        return max(1, min(_MAX_RESULT_LIMIT, value))


@dataclass(frozen=True)
class StatementSqlPlanResult:
    plan: Optional[StatementSqlPlan]
    resolver: StatementSqlResolver
    reason: str
