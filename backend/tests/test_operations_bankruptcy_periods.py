"""Tests for bankruptcy suspicion period windows."""

from datetime import date

from app.services.operations_bankruptcy_periods import (
    all_bankruptcy_period_windows,
    bankruptcy_period_window,
)


def test_bankruptcy_period_one_month():
    window = bankruptcy_period_window(date(2024, 3, 15), "1m")
    assert window.date_from == date(2024, 2, 15)
    assert window.date_to == date(2024, 3, 15)
    assert window.label == "1 месяц"


def test_bankruptcy_period_three_years():
    window = bankruptcy_period_window(date(2024, 3, 15), "3y")
    assert window.date_from == date(2021, 3, 15)
    assert window.date_to == date(2024, 3, 15)


def test_all_bankruptcy_period_windows_order():
    windows = all_bankruptcy_period_windows(date(2024, 1, 10))
    assert [window.period_id for window in windows] == ["1m", "6m", "1y", "3y"]
