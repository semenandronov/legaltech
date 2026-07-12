"""Tests for operations registry query helpers."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

from app.schemas.operations import build_summary, collect_column_headers, serialize_transaction
from app.services.case_file_transaction_service import CaseFileTransactionService


def _row(**kwargs):
    row = MagicMock()
    row.id = kwargs.get("id", "tx-1")
    row.file_id = kwargs.get("file_id", "file-1")
    row.source_filename = kwargs.get("source_filename", "stmt.pdf")
    row.global_row_index = kwargs.get("global_row_index", 0)
    row.operation_date = kwargs.get("operation_date")
    row.operation_datetime_text = kwargs.get("operation_datetime_text")
    row.amount_rub = kwargs.get("amount_rub")
    row.amount_raw = kwargs.get("amount_raw")
    row.description = kwargs.get("description")
    row.row_columns = kwargs.get("row_columns", {})
    row.page_start = kwargs.get("page_start")
    row.verbatim_row_text = kwargs.get("verbatim_row_text")
    row.source_references = kwargs.get("source_references")
    row.flow_direction = kwargs.get("flow_direction")
    row.char_start = kwargs.get("char_start")
    row.char_end = kwargs.get("char_end")
    return row


def test_serialize_transaction():
    payload = serialize_transaction(
        _row(
            operation_date=date(2024, 3, 15),
            amount_rub=Decimal("1500.50"),
            description="Оплата",
            row_columns={"Дата": "15.03.2024"},
        )
    )
    assert payload.operation_date == "2024-03-15"
    assert payload.amount_rub == 1500.5
    assert payload.description == "Оплата"
    assert payload.row_columns["Дата"] == "15.03.2024"


def test_collect_column_headers_single_file():
    rows = [
        _row(row_columns={"Дебет": "100", "Кредит": ""}),
        _row(row_columns={"Дебет": "", "Кредит": "200"}),
    ]
    headers = collect_column_headers(rows, single_file=True)
    assert "Дебет" in headers
    assert "Кредит" in headers


def test_collect_column_headers_coalesces_noisy_union():
    rows = [
        _row(
            row_columns={
                "Дата операции<br>¹": "10.01.2024",
                "Сумма в валюте карты": "-100",
            }
        ),
        _row(
            row_columns={
                "Дата операции ¹ Дата операции (МСК)": "11.01.2024",
                "Сумма в валюте карты Сумма списания": "-50",
            }
        ),
    ]
    headers = collect_column_headers(rows, single_file=True)
    assert headers == ["Дата операции", "Сумма в валюте карты"]


def test_serialize_transaction_normalizes_column_keys():
    payload = serialize_transaction(
        _row(
            row_columns={
                "Дата операции<br>¹": "15.03.2024",
                "Описание операции⁴": "Оплата",
            }
        )
    )
    assert payload.row_columns == {
        "Дата операции": "15.03.2024",
        "Описание операции": "Оплата",
    }


def test_build_summary():
    rows = [
        _row(operation_date=date(2024, 1, 1), amount_rub=Decimal("100")),
        _row(operation_date=date(2024, 2, 1), amount_rub=Decimal("250")),
    ]
    summary = build_summary(rows, total=10, file_id="f1")
    assert summary.total == 10
    assert summary.returned == 2
    assert summary.amount_sum_rub == 350.0
    assert summary.file_count == 1
    assert summary.date_min == "2024-01-01"
    assert summary.date_max == "2024-02-01"


def test_normalize_file_id_rejects_empty():
    from app.services.operations_registry_service import normalize_file_id
    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as exc:
        normalize_file_id("  ")
    assert exc.value.status_code == 400


def test_apply_query_filters_search_uses_description(monkeypatch):
    db = MagicMock()
    chain = MagicMock()
    db.query.return_value = chain
    chain.filter.return_value = chain
    chain.order_by.return_value = chain
    chain.offset.return_value = chain
    chain.limit.return_value = chain
    chain.all.return_value = []

    CaseFileTransactionService.query(
        db,
        case_id="case-1",
        file_ids=["f1"],
        description_contains="Иванов",
        limit=10,
    )
    assert chain.filter.called
