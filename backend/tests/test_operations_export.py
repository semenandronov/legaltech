"""Tests for operations CSV/Excel export."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.operations_export_service import (
    export_transactions_csv,
    export_transactions_excel,
)


def _row(**kwargs):
    defaults = dict(
        operation_datetime_text="01.02.2024",
        operation_date=date(2024, 2, 1),
        amount_raw="100,00",
        amount_rub=None,
        description="Оплата",
        source_filename="stmt.pdf",
        row_columns={"Дата": "01.02.2024", "Сумма": "100,00", "Описание": "Оплата"},
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_export_csv_single_file_uses_statement_columns():
    raw = export_transactions_csv([_row()], single_file=True)
    text = raw.decode("utf-8-sig")
    assert "Дата" in text
    assert "Описание" in text
    assert "Оплата" in text
    assert text.startswith("№") or "№" in text.splitlines()[0]


def test_export_excel_is_zip_container():
    raw = export_transactions_excel([_row(), _row(description="Вторая")], single_file=True)
    assert raw[:2] == b"PK"
    assert len(raw) > 100


def test_fetch_ordered_by_ids_preserves_order(monkeypatch):
    from app.services.case_file_transaction_service import CaseFileTransactionService

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *a, **k):
            return self

        def all(self):
            return self._rows

    class FakeDB:
        def query(self, model):
            return FakeQuery(
                [
                    SimpleNamespace(id="b", case_id="c", file_id="f"),
                    SimpleNamespace(id="a", case_id="c", file_id="f"),
                ]
            )

    ordered = CaseFileTransactionService.fetch_ordered_by_ids(
        FakeDB(),
        case_id="c",
        file_id="f",
        transaction_ids=["a", "missing", "b"],
    )
    assert [r.id for r in ordered] == ["a", "b"]
