"""Ingest pipeline uses passport-only classification (no standalone classifier)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services import file_processor_bg as fpb


def _file_row(**kwargs):
    defaults = dict(
        id="fid-1",
        filename="00. возражения.pdf",
        file_path="case-1/doc.pdf",
        file_content=None,
        processing_status="pending",
        processing_started_at=None,
        original_text=None,
        doc_summary_short=None,
        doc_key_points=None,
        summary_version=None,
        summary_content_hash=None,
        processing_error=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_process_one_file_skips_standalone_classifier(monkeypatch):
    file_row = _file_row()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = file_row

    classifier_called = False

    class _Classifier:
        def classify_document(self, **_kwargs):
            nonlocal classifier_called
            classifier_called = True
            return {"doc_type": "other"}

    monkeypatch.setattr(
        "app.services.document_classifier_service.DocumentClassifierService",
        _Classifier,
    )

    passport_calls: list[dict] = []

    def _fake_passport(**kwargs):
        passport_calls.append(kwargs)
        return ("summary text long enough for validation purposes here.", ["a", "b"], "возражение", "v3_langgraph_llm")

    monkeypatch.setattr(fpb, "_generate_llm_document_passport", _fake_passport)

    doc_processor = MagicMock()
    doc_processor.split_documents.return_value = [MagicMock(metadata={})]
    doc_processor.store_in_vector_db.return_value = None

    with patch("app.services.case_file_bytes.load_case_file_bytes", return_value=b"%PDF"):
        with patch(
            "app.services.langchain_loaders.DocumentLoaderService.load_document",
            return_value=[SimpleNamespace(page_content="текст документа " * 20)],
        ):
            with patch.object(fpb, "_persist_passport_classification") as persist:
                with patch(
                    "app.services.chat.entity_index_service.merge_case_entity_index",
                ):
                    fpb._process_one_file(db, "fid-1", "case-1", doc_processor)

    assert classifier_called is False
    assert len(passport_calls) == 1
    assert passport_calls[0]["hint_doc_type"] == "возражение"
    persist.assert_called_once()
    assert persist.call_args.kwargs["doc_type"] == "возражение"
