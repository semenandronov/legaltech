"""Tabular export helpers / options."""

from app.services.tabular_review_service import (
    TabularReviewService,
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


def test_clean_export_value_preserves_na_vs_blank():
    clean = TabularReviewService._clean_export_value
    assert clean("N/A") == "—"
    assert clean("нет данных") == "—"
    assert clean("Н/Д") == "—"
    assert clean("Не найдено") == "—"
    assert clean("—") == "—"
    assert clean("-") == ""
    assert clean("") == ""
    assert clean(None) == ""
    assert clean("ООО Ромашка") == "ООО Ромашка"
    assert clean('{"cell_value": "N/A"}') == "—"
    assert clean('{"cell_value": "123"}') == "123"
