"""Tests for transaction row PDF source contract."""

from langchain_core.documents import Document

from app.services.case_file_transaction_service import parse_row_from_document
from app.services.transaction_source import (
    build_highlight_fragments,
    build_verbatim_row_text,
    resolve_row_source_for_db_row,
)


def test_build_verbatim_row_text_from_columns():
    text = build_verbatim_row_text(
        {
            "Дата": "15.03.2024",
            "Дебет": "1 000,00",
            "Назначение": "Оплата",
        },
        column_order=["Дата", "Дебет", "Назначение"],
    )
    assert "15.03.2024" in text
    assert "1 000,00" in text
    assert "Оплата" in text


def test_build_highlight_fragments_prefers_cell_values_before_labeled_verbatim():
    fragments = build_highlight_fragments(
        {
            "Дата": "15.03.2024",
            "Дебет": "500 000,00",
            "Назначение платежа": "Перевод контрагенту",
        },
        verbatim_row_text="Дата: 15.03.2024\nДебет: 500 000,00\nНазначение платежа: Перевод контрагенту",
    )
    assert fragments[0] == "Перевод контрагенту"
    assert "500 000,00" in fragments
    assert fragments[-1].startswith("Дата:")


def test_highlight_targets_from_row_metadata_excel_chunk():
    from app.services.transaction_source import highlight_targets_from_row_metadata

    targets = highlight_targets_from_row_metadata(
        {
            "chunk_level": "row",
            "row_columns": {
                "Дата": "24.06.2026",
                "Сумма": "1000.50",
                "Назначение платежа": "Оплата по договору 1",
            },
        },
        page_content="Дата: 24.06.2026\nСумма: 1000.50\nНазначение платежа: Оплата по договору 1",
    )
    assert targets[0] == "Оплата по договору 1"
    assert "1000.50" in targets


def test_resolve_row_source_legacy_row_without_db_fields():
    verbatim, refs, fragments = resolve_row_source_for_db_row(
        row_columns={"Дебет": "100,00", "Назначение": "Тест"},
        verbatim_row_text=None,
        source_references=None,
        page_start=2,
        char_start=None,
        char_end=None,
        description="Тест",
    )
    assert "100,00" in verbatim
    assert refs[0]["page"] == 2
    assert fragments


def test_parse_row_from_document_extracts_source_fields():
    doc = Document(
        page_content="Дата: 01.01.2024\nДебет: 100,00\nНазначение: Аренда",
        metadata={
            "chunk_level": "row",
            "global_row_index": 3,
            "table_index": 0,
            "row_index": 3,
            "page_start": 5,
            "char_start": 100,
            "char_end": 180,
            "row_columns": {
                "Дата": "01.01.2024",
                "Дебет": "100,00",
                "Назначение": "Аренда",
            },
        },
    )
    row = parse_row_from_document(doc)
    assert row is not None
    assert row.flow_direction == "debit"
    assert row.amount_rub is not None
    assert row.verbatim_row_text
    assert "Аренда" in row.verbatim_row_text
    assert row.source_references
