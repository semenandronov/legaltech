"""Native Excel → structured_table row chunks for Operations registry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    rows_from_documents,
)
from app.services.document_indexing import build_index_chunks
from app.services.xlsx_structured_indexer import try_index_xlsx_as_structured_table


def _bank_statement_xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Выписка"
    ws.append(["Дата", "Сумма", "Назначение платежа"])
    rows = [
        (date(2026, 6, 24), 1000.50, "Оплата по договору 1"),
        (date(2026, 6, 24), 2500.00, "Оплата по договору 2"),
        (date(2026, 6, 25), 3400.00, "Возврат средств"),
        (date(2026, 6, 26), 500.25, "Комиссия банка"),
        (date(2026, 6, 27), 1200.00, "Перевод контрагенту А"),
        (date(2026, 6, 28), 900.00, "Перевод контрагенту Б"),
        (date(2026, 6, 29), 150.00, "СМС-информирование"),
        (date(2026, 6, 30), 750.75, "Оплата аренды"),
    ]
    for row in rows:
        ws.append(list(row))
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_structured_indexer_emits_row_chunks(monkeypatch):
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.XLSX_STRUCTURED_TABLE_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.STRUCTURED_TABLE_INDEXING_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.STRUCTURED_TABLE_MIN_ROWS",
        8,
        raising=False,
    )

    content = _bank_statement_xlsx_bytes()
    docs = try_index_xlsx_as_structured_table(
        content_bytes=content,
        filename="statement.xlsx",
        base_metadata={"doc_id": "f1", "file_id": "f1", "case_id": "c1"},
    )
    assert docs is not None
    assert len(docs) == 8
    assert all(d.metadata.get("index_profile") == "structured_table" for d in docs)
    assert all(d.metadata.get("chunk_level") == "row" for d in docs)
    assert docs[0].metadata.get("row_columns", {}).get("Дата") == "24.06.2026"


def test_build_index_chunks_routes_xlsx(monkeypatch):
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.XLSX_STRUCTURED_TABLE_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.STRUCTURED_TABLE_INDEXING_ENABLED",
        True,
        raising=False,
    )

    docs = build_index_chunks(
        content_bytes=_bank_statement_xlsx_bytes(),
        filename="bank.xlsx",
        base_metadata={"doc_id": "f2", "file_id": "f2"},
    )
    assert len(docs) == 8
    assert docs[0].metadata.get("preseg_strategy") == "xlsx_openpyxl_grid"


def test_xlsx_rows_parse_into_transactions(monkeypatch):
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.XLSX_STRUCTURED_TABLE_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.STRUCTURED_TABLE_INDEXING_ENABLED",
        True,
        raising=False,
    )

    docs = build_index_chunks(
        content_bytes=_bank_statement_xlsx_bytes(),
        filename="bank.xlsx",
        base_metadata={"doc_id": "f3", "file_id": "f3"},
    )
    parsed = rows_from_documents(docs)
    assert len(parsed) == 8
    assert parsed[0].operation_date == date(2026, 6, 24)
    assert parsed[0].amount_rub == Decimal("1000.50")
    assert "договору 1" in (parsed[0].description or "")


def test_sync_from_documents_xlsx(db_session, test_case, monkeypatch):
    monkeypatch.setenv("CASE_FILE_TRANSACTIONS_ENABLED", "true")
    from app import config as config_module

    config_module.config.CASE_FILE_TRANSACTIONS_ENABLED = True
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.XLSX_STRUCTURED_TABLE_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.xlsx_structured_indexer.config.STRUCTURED_TABLE_INDEXING_ENABLED",
        True,
        raising=False,
    )

    file_id = "xlsx-ops-file"
    docs = build_index_chunks(
        content_bytes=_bank_statement_xlsx_bytes(),
        filename="bank.xlsx",
        base_metadata={"doc_id": file_id, "file_id": file_id, "case_id": test_case.id},
    )
    count = CaseFileTransactionService.sync_from_documents(
        db_session,
        case_id=test_case.id,
        file_id=file_id,
        filename="bank.xlsx",
        documents=docs,
    )
    assert count == 8
    rows = CaseFileTransactionService.query(
        db_session,
        case_id=test_case.id,
        file_id=file_id,
        on_date=date(2026, 6, 24),
    )
    assert len(rows) == 2
    CaseFileTransactionService.delete_for_file(db_session, file_id)
