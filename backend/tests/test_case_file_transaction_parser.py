"""Unit tests for case file transaction parsing (no DB)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.case_file_transaction_service import (
    filter_parsed_rows,
    parse_amount_rub,
    parse_operation_date,
    parse_row_from_metadata,
    rows_from_documents,
)
from app.services.document_indexing import build_index_chunks

PDF_PATH = Path("/Users/semyon_andronov04/Downloads/funds_movement.pdf")


def test_parse_row_from_metadata_uses_category_as_description():
    parsed = parse_row_from_metadata(
        {
            "chunk_level": "row",
            "global_row_index": 0,
            "table_index": 0,
            "row_index": 0,
            "row_columns": {
                "Дата Операции (МСК)": "20.06.2026",
                "Категория": "Оплата по QR-коду СБП Сервисы Яндекса. Операция по карте ****7035",
                "Сумма В Валюте Счёта": "1 720,00",
                "Остаток Средств": "5 694,16",
            },
        }
    )
    assert parsed is not None
    assert parsed.description and "Сервисы Яндекса" in parsed.description
    assert parsed.amount_rub == Decimal("1720.00")
    assert parsed.operation_date == date(2026, 6, 20)



def test_parse_amount_rub_negative():
    amount, raw = parse_amount_rub("-3 100.00 ₽")
    assert amount == Decimal("-3100.00")
    assert "3 100" in raw


@pytest.mark.skipif(not PDF_PATH.is_file(), reason="funds_movement.pdf not available locally")
def test_funds_movement_rows_filter_by_date():
    docs = build_index_chunks(
        content_bytes=PDF_PATH.read_bytes(),
        filename="funds_movement.pdf",
        base_metadata={"doc_id": "f1", "file_id": "f1", "case_id": "c1"},
        loader_native_text=True,
    )
    parsed = rows_from_documents(docs)
    assert len(parsed) >= 300

    on_day = filter_parsed_rows(parsed, on_date=date(2026, 6, 24))
    assert len(on_day) == 3

    descriptions = {r.description for r in on_day}
    assert any("ANTI" in (d or "").upper() for d in descriptions)
    assert any("Сбер" in (d or "") for d in descriptions)
    assert any("договор" in (d or "").lower() for d in descriptions)


@pytest.mark.skipif(not PDF_PATH.is_file(), reason="funds_movement.pdf not available locally")
def test_parse_row_from_tbank_metadata():
    docs = build_index_chunks(
        content_bytes=PDF_PATH.read_bytes(),
        filename="funds_movement.pdf",
        base_metadata={"file_id": "f1"},
        loader_native_text=True,
    )
    row_doc = next(d for d in docs if d.metadata.get("chunk_level") == "row")
    parsed = parse_row_from_metadata(row_doc.metadata)
    assert parsed is not None
    assert parsed.operation_date is not None
    assert parsed.amount_rub is not None
    assert parsed.description
