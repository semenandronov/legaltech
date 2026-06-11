"""Russian Federation business-day calendar for draft financial calculations."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Literal, Set

TermCountStarts = Literal["next_day", "same_day"]
CalendarMode = Literal["statutory", "production"]

# Statutory non-working holidays (TK RF art. 112) — used for «рабочие дни» in contracts.
_RF_STATUTORY_HOLIDAYS: Set[date] = {
    # 2024
    date(2024, 1, 1),
    date(2024, 1, 2),
    date(2024, 1, 3),
    date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 6),
    date(2024, 1, 7),
    date(2024, 1, 8),
    date(2024, 2, 23),
    date(2024, 3, 8),
    date(2024, 5, 1),
    date(2024, 5, 9),
    date(2024, 6, 12),
    date(2024, 11, 4),
    # 2025
    date(2025, 1, 1),
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 4),
    date(2025, 1, 5),
    date(2025, 1, 6),
    date(2025, 1, 7),
    date(2025, 1, 8),
    date(2025, 2, 23),
    date(2025, 3, 8),
    date(2025, 5, 1),
    date(2025, 5, 9),
    date(2025, 6, 12),
    date(2025, 11, 4),
    # 2026
    date(2026, 1, 1),
    date(2026, 1, 2),
    date(2026, 1, 3),
    date(2026, 1, 4),
    date(2026, 1, 5),
    date(2026, 1, 6),
    date(2026, 1, 7),
    date(2026, 1, 8),
    date(2026, 2, 23),
    date(2026, 3, 8),
    date(2026, 5, 1),
    date(2026, 5, 9),
    date(2026, 6, 12),
    date(2026, 11, 4),
    # 2027 (baseline; extend when official calendar published)
    date(2027, 1, 1),
    date(2027, 1, 2),
    date(2027, 1, 3),
    date(2027, 1, 4),
    date(2027, 1, 5),
    date(2027, 1, 6),
    date(2027, 1, 7),
    date(2027, 1, 8),
    date(2027, 2, 23),
    date(2027, 3, 8),
    date(2027, 5, 1),
    date(2027, 5, 9),
    date(2027, 6, 12),
    date(2027, 11, 4),
}

# Extra non-working days from government transfer decrees (production calendar).
_RF_TRANSFERRED_DAYS: Set[date] = {
    date(2024, 5, 10),
    date(2024, 12, 31),
    date(2025, 5, 2),
    date(2025, 6, 13),
    date(2025, 11, 3),
    date(2025, 12, 31),
    date(2026, 3, 9),
    date(2026, 5, 11),
    date(2026, 12, 31),
    date(2027, 5, 10),
    date(2027, 6, 14),
}

_RF_PRODUCTION_HOLIDAYS = _RF_STATUTORY_HOLIDAYS | _RF_TRANSFERRED_DAYS


def _holidays_for_mode(calendar_mode: CalendarMode) -> Set[date]:
    if calendar_mode == "production":
        return _RF_PRODUCTION_HOLIDAYS
    return _RF_STATUTORY_HOLIDAYS


def is_weekend(d: date) -> bool:
    return d.weekday() >= 5


def is_holiday(
    d: date,
    extra_holidays: Iterable[date] | None = None,
    *,
    calendar_mode: CalendarMode = "statutory",
) -> bool:
    holidays = _holidays_for_mode(calendar_mode)
    if d in holidays:
        return True
    if extra_holidays:
        return d in set(extra_holidays)
    return False


def is_business_day(
    d: date,
    extra_holidays: Iterable[date] | None = None,
    *,
    calendar_mode: CalendarMode = "statutory",
) -> bool:
    return not is_weekend(d) and not is_holiday(d, extra_holidays, calendar_mode=calendar_mode)


def next_business_day(
    d: date,
    extra_holidays: Iterable[date] | None = None,
    *,
    calendar_mode: CalendarMode = "statutory",
) -> date:
    cur = d + timedelta(days=1)
    while not is_business_day(cur, extra_holidays, calendar_mode=calendar_mode):
        cur += timedelta(days=1)
    return cur


def add_business_days(
    start: date,
    count: int,
    *,
    term_count_starts: TermCountStarts = "next_day",
    extra_holidays: Iterable[date] | None = None,
    calendar_mode: CalendarMode = "statutory",
) -> date:
    """
    Add ``count`` Russian business days to ``start``.

    ``term_count_starts``:
    - ``next_day``: first business day after ``start`` is day 1 (typical for «с момента подписания»).
    - ``same_day``: if ``start`` is a business day it counts as day 1.

    ``calendar_mode``:
    - ``statutory``: TK RF art. 112 holidays only (default for contract «рабочие дни»).
    - ``production``: includes government transfer days off.
    """
    if count <= 0:
        return start

    if term_count_starts == "next_day":
        cur = start + timedelta(days=1)
    else:
        cur = start

    remaining = count
    while remaining > 0:
        if is_business_day(cur, extra_holidays, calendar_mode=calendar_mode):
            remaining -= 1
            if remaining == 0:
                return cur
        cur += timedelta(days=1)

    return cur


def payment_deadline_and_penalty_start(
    event_date: date,
    business_days: int,
    *,
    term_count_starts: TermCountStarts = "next_day",
    calendar_mode: CalendarMode = "statutory",
) -> tuple[date, date]:
    """Return (last day to pay without penalty, first penalty day)."""
    deadline = add_business_days(
        event_date,
        business_days,
        term_count_starts=term_count_starts,
        calendar_mode=calendar_mode,
    )
    penalty_start = deadline + timedelta(days=1)
    return deadline, penalty_start


def count_penalty_days(penalty_start: date, penalty_end: date) -> int:
    """
    Inclusive calendar days of delay for daily contractual penalty.

    Both ``penalty_start`` (first overdue day) and ``penalty_end`` (as-of / claim date) accrue.
    """
    if penalty_end < penalty_start:
        return 0
    return (penalty_end - penalty_start).days + 1
