"""Integration: ingest funds_movement.pdf rows into case_file_transactions."""

from datetime import date
from pathlib import Path

import pytest

from app.models.case_file_transaction import CaseFileTransaction  # noqa: F401 — register model
from app.services.case_file_transaction_service import CaseFileTransactionService
from app.services.document_indexing import build_index_chunks

PDF_PATH = Path("/Users/semyon_andronov04/Downloads/funds_movement.pdf")


@pytest.mark.skipif(not PDF_PATH.is_file(), reason="funds_movement.pdf not available locally")
def test_sync_and_query_funds_movement_24_06(db_session, test_case, monkeypatch):
    monkeypatch.setenv("CASE_FILE_TRANSACTIONS_ENABLED", "true")
    from app import config as config_module

    config_module.config.CASE_FILE_TRANSACTIONS_ENABLED = True

    case_id = test_case.id
    file_id = "test-file-funds-movement"

    docs = build_index_chunks(
        content_bytes=PDF_PATH.read_bytes(),
        filename="funds_movement.pdf",
        base_metadata={"doc_id": file_id, "file_id": file_id, "case_id": case_id},
        loader_native_text=True,
    )

    count = CaseFileTransactionService.sync_from_documents(
        db_session,
        case_id=case_id,
        file_id=file_id,
        filename="funds_movement.pdf",
        documents=docs,
    )
    assert count >= 300

    rows = CaseFileTransactionService.query(
        db_session,
        case_id=case_id,
        file_id=file_id,
        on_date=date(2026, 6, 24),
    )
    assert len(rows) == 3

    agg = CaseFileTransactionService.aggregate(
        db_session,
        case_id=case_id,
        file_id=file_id,
        on_date=date(2026, 6, 24),
    )
    assert agg["count"] == 3
    assert float(agg["amount_sum_rub"]) == pytest.approx(5900.0, rel=0, abs=0.01)

    CaseFileTransactionService.delete_for_file(db_session, file_id)
