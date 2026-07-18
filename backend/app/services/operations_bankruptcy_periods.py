"""Bankruptcy suspicion period windows relative to court petition acceptance date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from dateutil.relativedelta import relativedelta

BankruptcySuspicionPeriodId = Literal["1m", "6m", "1y", "3y"]

BANKRUPTCY_SUSPICION_PERIODS: tuple[tuple[BankruptcySuspicionPeriodId, str, int], ...] = (
    ("1m", "1 месяц", 1),
    ("6m", "6 месяцев", 6),
    ("1y", "1 год", 12),
    ("3y", "3 года", 36),
)


@dataclass(frozen=True)
class BankruptcySuspicionWindow:
    period_id: BankruptcySuspicionPeriodId
    label: str
    date_from: date
    date_to: date


def bankruptcy_period_window(
    petition_date: date,
    period_id: BankruptcySuspicionPeriodId,
) -> BankruptcySuspicionWindow:
    """Inclusive date range [date_from, date_to] ending on petition acceptance date."""
    months = next(months for pid, _label, months in BANKRUPTCY_SUSPICION_PERIODS if pid == period_id)
    label = next(label for pid, label, _months in BANKRUPTCY_SUSPICION_PERIODS if pid == period_id)
    date_from = petition_date - relativedelta(months=months)
    return BankruptcySuspicionWindow(
        period_id=period_id,
        label=label,
        date_from=date_from,
        date_to=petition_date,
    )


def all_bankruptcy_period_windows(petition_date: date) -> list[BankruptcySuspicionWindow]:
    return [bankruptcy_period_window(petition_date, period_id) for period_id, _label, _months in BANKRUPTCY_SUSPICION_PERIODS]


def parse_bankruptcy_period_id(value: Optional[str]) -> Optional[BankruptcySuspicionPeriodId]:
    normalized = (value or "").strip().lower()
    if normalized in ("1m", "6m", "1y", "3y"):
        return normalized  # type: ignore[return-value]
    return None
