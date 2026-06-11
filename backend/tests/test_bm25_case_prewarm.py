"""BM25 prewarm из PGVector — индекс в процессе API без «index absent»."""
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.services.bm25_case_prewarm import (
    cancel_pending_bm25_prewarm,
    ensure_bm25_index,
    finalize_case_bm25_after_ingestion,
    prepare_bm25_for_tabular_extraction,
    schedule_bm25_prewarm,
)


def test_ensure_bm25_index_loads_from_pgvector():
    dp = MagicMock()
    dp.bm25_retriever.available = True
    dp.bm25_retriever.has_index.return_value = False
    dp.prewarm_bm25_from_store.return_value = True

    ok = ensure_bm25_index(dp, "case-1")

    assert ok is True
    dp.prewarm_bm25_from_store.assert_called_once_with("case-1", force_rebuild=False)


def test_prewarm_bm25_from_store_uses_list_case_chunks():
    from app.services.document_processor import DocumentProcessor

    dp = MagicMock()
    dp.bm25_retriever.available = True
    dp.bm25_retriever.has_index.return_value = False
    dp.vector_store.list_case_chunks.return_value = [
        Document(page_content="ИНН 7701000000", metadata={"file_id": "f1"}),
    ]
    dp.prewarm_bm25_index.return_value = True

    ok = DocumentProcessor.prewarm_bm25_from_store(dp, "case-1")

    assert ok is True
    dp.vector_store.list_case_chunks.assert_called_once()
    dp.prewarm_bm25_index.assert_called_once()


def test_schedule_bm25_prewarm_uses_debounced_timer():
    with patch("app.services.bm25_case_prewarm._debounce_sec", return_value=1.5):
        with patch("threading.Timer") as timer_cls:
            timer = MagicMock()
            timer_cls.return_value = timer
            schedule_bm25_prewarm("case-2", force_rebuild=True)
            timer_cls.assert_called_once()
            assert timer_cls.call_args[0][0] == 1.5
            timer.start.assert_called_once()


def test_finalize_case_bm25_cancels_debounce_and_rebuilds_from_store():
    dp = MagicMock()
    dp.bm25_retriever.available = True
    dp.prewarm_bm25_from_store.return_value = True

    with patch("app.services.bm25_case_prewarm.cancel_pending_bm25_prewarm") as cancel:
        with patch("app.services.bm25_case_prewarm.invalidate_bm25_index") as invalidate:
            ok = finalize_case_bm25_after_ingestion("case-3", dp)

    assert ok is True
    cancel.assert_called_once_with("case-3")
    invalidate.assert_called_once_with("case-3", dp)
    dp.prewarm_bm25_from_store.assert_called_once_with("case-3", force_rebuild=True)


def test_prepare_bm25_for_tabular_extraction_schedules_when_missing():
    dp = MagicMock()
    dp.bm25_retriever.available = True
    dp.bm25_retriever.has_index.return_value = False

    with patch("app.services.bm25_case_prewarm.schedule_bm25_prewarm") as schedule:
        ready = prepare_bm25_for_tabular_extraction(dp, "case-tab")

    assert ready is False
    schedule.assert_called_once_with("case-tab")


def test_prepare_bm25_for_tabular_extraction_returns_true_when_ready():
    dp = MagicMock()
    dp.bm25_retriever.available = True
    dp.bm25_retriever.has_index.return_value = True

    with patch("app.services.bm25_case_prewarm.schedule_bm25_prewarm") as schedule:
        ready = prepare_bm25_for_tabular_extraction(dp, "case-tab")

    assert ready is True
    schedule.assert_not_called()


def test_cancel_pending_bm25_prewarm_cancels_timer():
    import app.services.bm25_case_prewarm as mod

    timer = MagicMock()
    mod._debounce_timers["case-x"] = timer
    mod._pending_force["case-x"] = True

    cancel_pending_bm25_prewarm("case-x")

    timer.cancel.assert_called_once()
    assert "case-x" not in mod._debounce_timers
    assert "case-x" not in mod._pending_force
