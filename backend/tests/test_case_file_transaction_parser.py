"""Unit tests for case file transaction parsing (no DB)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import (
    filter_parsed_rows,
    parse_amount_rub,
    parse_operation_date,
    parse_row_from_metadata,
    rows_from_documents,
)
from app.services.chat.statement_analytics import compute_overview
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
    # Unsigned card spend → debit (negative).
    assert parsed.amount_rub == Decimal("-1720.00")
    assert parsed.flow_direction == "debit"
    assert parsed.operation_date == date(2026, 6, 20)


def test_parse_card_statement_credit_with_plus():
    parsed = parse_row_from_metadata(
        {
            "chunk_level": "row",
            "global_row_index": 1,
            "table_index": 0,
            "row_index": 1,
            "row_columns": {
                "Дата": "02.06.2026 20:17",
                "Категория": "Пополнение. Операция по счету",
                "Сумма": "+2 000,00",
                "Остаток": "12 000,00",
            },
        }
    )
    assert parsed is not None
    assert parsed.amount_rub == Decimal("2000.00")
    assert parsed.flow_direction == "credit"


def test_parse_card_statement_unsigned_spend():
    parsed = parse_row_from_metadata(
        {
            "chunk_level": "row",
            "global_row_index": 2,
            "table_index": 0,
            "row_index": 2,
            "row_columns": {
                "Дата": "02.06.2026 20:48",
                "Категория": "Супермаркеты MAGAZIN KEDR. Операция по карте",
                "Сумма": "305,00",
                "Остаток": "11 695,00",
            },
        }
    )
    assert parsed is not None
    assert parsed.amount_rub == Decimal("-305.00")
    assert parsed.flow_direction == "debit"


def test_parse_separate_debit_credit_columns():
    debit_row = parse_row_from_metadata(
        {
            "chunk_level": "row",
            "global_row_index": 0,
            "table_index": 0,
            "row_index": 0,
            "row_columns": {
                "Дата": "01.01.2026",
                "Описание": "Оплата поставщику",
                "Дебет": "10 000,00",
                "Кредит": "",
            },
        }
    )
    assert debit_row is not None
    assert debit_row.amount_rub == Decimal("-10000.00")
    assert debit_row.flow_direction == "debit"

    credit_row = parse_row_from_metadata(
        {
            "chunk_level": "row",
            "global_row_index": 1,
            "table_index": 0,
            "row_index": 1,
            "row_columns": {
                "Дата": "01.01.2026",
                "Описание": "Поступление от клиента",
                "Дебет": "",
                "Кредит": "10 000,00",
            },
        }
    )
    assert credit_row is not None
    assert credit_row.amount_rub == Decimal("10000.00")
    assert credit_row.flow_direction == "credit"


def test_parse_amount_rub_negative():
    amount, raw = parse_amount_rub("-3 100.00 ₽")
    assert amount == Decimal("-3100.00")
    assert "3 100" in raw


def test_analytics_overview_on_legacy_unsigned_card_rows():
    """Chat must recover signs from amount_raw even if DB still has legacy positives."""
    rows = [
        CaseFileTransaction(
            id="c1",
            case_id="case",
            file_id="f1",
            global_row_index=0,
            table_index=0,
            row_index=0,
            amount_rub=Decimal("2000"),
            amount_raw="+2 000,00",
            description="Пополнение",
            row_columns={},
        ),
        CaseFileTransaction(
            id="d1",
            case_id="case",
            file_id="f1",
            global_row_index=1,
            table_index=0,
            row_index=1,
            amount_rub=Decimal("305"),
            amount_raw="305,00",
            description="Супермаркеты MAGAZIN",
            row_columns={},
        ),
        CaseFileTransaction(
            id="d2",
            case_id="case",
            file_id="f1",
            global_row_index=2,
            table_index=0,
            row_index=2,
            amount_rub=Decimal("1720"),
            amount_raw="1 720,00",
            description="Оплата по QR-коду СБП",
            row_columns={},
        ),
    ]
    ov = compute_overview(rows)
    assert ov.flow.inflow_count == 1
    assert ov.flow.outflow_count == 2
    assert ov.flow.inflow_sum == Decimal("2000")
    assert ov.flow.outflow_sum == Decimal("2025")
    assert ov.flow.net_sum == Decimal("-25")


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
    assert len(on_day) >= 1
    # Every parsed row must carry a signed amount + flow after normalize.
    assert all(r.amount_rub is not None for r in on_day)
    assert all(r.flow_direction in {"debit", "credit"} for r in on_day if r.amount_rub)


@pytest.mark.skipif(not PDF_PATH.is_file(), reason="funds_movement.pdf not available locally")
def test_parse_row_from_tbank_metadata():
    docs = build_index_chunks(
        content_bytes=PDF_PATH.read_bytes(),
        filename="funds_movement.pdf",
        base_metadata={"file_id": "f1"},
        loader_native_text=True,
    )
    row_docs = [d for d in docs if d.metadata.get("chunk_level") == "row"]
    assert row_docs
    parsed_rows = [parse_row_from_metadata(d.metadata) for d in row_docs[:20]]
    parsed_rows = [r for r in parsed_rows if r is not None]
    assert parsed_rows
    assert any(r.operation_date is not None for r in parsed_rows)
    assert any(r.amount_rub is not None for r in parsed_rows)
    # Signed convention: debits negative, credits positive.
    for r in parsed_rows:
        if r.amount_rub is None or r.amount_rub == 0:
            continue
        if r.flow_direction == "debit":
            assert r.amount_rub < 0
        if r.flow_direction == "credit":
            assert r.amount_rub > 0
