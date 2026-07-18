"""Heuristic filter for routine operational bank statement rows (taxes, payroll, rent)."""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from sqlalchemy import String, cast, func, not_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models.case_file_transaction import CaseFileTransaction

# Substrings matched case-insensitively against description + row column text.
OPERATIONAL_NOISE_SUBSTRINGS: tuple[str, ...] = (
    "ндфл",
    "налог",
    "фнс",
    "ифнс",
    "сфр",
    "пфр",
    "фсс",
    "страхов",
    "взнос",
    "аренд",
    "коммунал",
    "жкх",
    "электроэнерг",
    "водоканал",
    "теплоснаб",
    "зарплат",
    "заработн",
    "оплата труда",
    "банковск",
    "обслуживан",
    "комисси",
    "эквайр",
    "интернет",
    "связь",
    "канцеляр",
)

_NOISE_REGEX = re.compile(
    "|".join(re.escape(token) for token in OPERATIONAL_NOISE_SUBSTRINGS),
    re.IGNORECASE,
)


def operational_noise_haystack(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def is_operational_noise_text(text: str) -> bool:
    return bool(_NOISE_REGEX.search(text or ""))


def is_operational_noise_row(
    *,
    description: str | None,
    row_columns: dict | None = None,
    operation_datetime_text: str | None = None,
    amount_raw: str | None = None,
) -> bool:
    columns = row_columns if isinstance(row_columns, dict) else {}
    column_text = " ".join(str(value) for value in columns.values() if value is not None)
    haystack = operational_noise_haystack(description, column_text, operation_datetime_text, amount_raw)
    return is_operational_noise_text(haystack)


def sql_operational_noise_match_expression() -> ColumnElement:
    """SQL expression that is true when a row looks like routine operational noise."""
    haystack = func.lower(
        func.concat(
            func.coalesce(CaseFileTransaction.description, ""),
            " ",
            func.coalesce(cast(CaseFileTransaction.row_columns, String), ""),
            " ",
            func.coalesce(CaseFileTransaction.operation_datetime_text, ""),
            " ",
            func.coalesce(CaseFileTransaction.amount_raw, ""),
        )
    )
    return or_(*(haystack.like(f"%{token}%") for token in OPERATIONAL_NOISE_SUBSTRINGS))


def sql_exclude_operational_noise() -> ColumnElement:
    return not_(sql_operational_noise_match_expression())


def count_operational_noise_matches(
    texts: Iterable[str],
) -> int:
    return sum(1 for text in texts if is_operational_noise_text(text))
