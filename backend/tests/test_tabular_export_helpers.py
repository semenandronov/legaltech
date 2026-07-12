"""Tabular export helpers / options."""

from app.services.tabular_review_service import (
    _column_additional_context,
    sanitize_sheet_title,
)


def test_sanitize_sheet_title():
    assert len(sanitize_sheet_title("A" * 100)) == 31
    assert "/" not in sanitize_sheet_title("a/b?c")


def test_column_additional_context_reads_config():
    assert _column_additional_context({"column_config": {"additional_context": "  x  "}}) == "x"
    assert _column_additional_context({"column_config": None}) == ""
    assert _column_additional_context({}) == ""
