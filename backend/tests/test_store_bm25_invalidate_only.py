"""store_in_vector_db: defer BM25 rebuild during file batch ingestion."""
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document


def test_store_in_vector_db_invalidate_only_skips_schedule():
    from app.services.document_processor import DocumentProcessor

    dp = MagicMock()
    dp.vector_store = MagicMock()
    dp.vector_store.add_documents.return_value = ["id1"]
    dp.vector_store.collection_name = "legal_ai_vault_vectors"

    docs = [Document(page_content="текст", metadata={"file_id": "f1"})]

    with patch("app.services.document_processor.config") as cfg:
        cfg.CASE_BM25_PREWARM_ENABLED = True
        with patch("app.services.bm25_case_prewarm.invalidate_bm25_index") as invalidate:
            with patch("app.services.bm25_case_prewarm.schedule_bm25_prewarm") as schedule:
                DocumentProcessor.store_in_vector_db(
                    dp,
                    "case-1",
                    docs,
                    db=MagicMock(),
                    bm25_after_store="invalidate_only",
                )

    invalidate.assert_called_once()
    schedule.assert_not_called()
