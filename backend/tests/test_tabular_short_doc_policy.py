"""Short-document full-text policy for tabular cells."""

from app.services.tabular_short_doc_policy import (
    build_short_doc_cell_context,
    should_use_short_doc_full_text,
)


def test_short_doc_triggers_below_budget(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_short_doc_policy.config.TABULAR_SHORT_DOC_FULL_TEXT",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.tabular_short_doc_policy.config.TABULAR_SHORT_DOC_MAX_CHARS",
        5000,
        raising=False,
    )
    assert should_use_short_doc_full_text("x" * 500)
    assert not should_use_short_doc_full_text("x" * 6000)


def test_short_doc_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.services.tabular_short_doc_policy.config.TABULAR_SHORT_DOC_FULL_TEXT",
        False,
        raising=False,
    )
    assert not should_use_short_doc_full_text("короткий документ")


def test_build_short_doc_context_metadata():
    text = "Договор аренды № 1"
    ctx, docs = build_short_doc_cell_context(
        original_text=text,
        file_id="f1",
        filename="lease.txt",
    )
    assert ctx == text
    assert len(docs) == 1
    assert docs[0].metadata["retrieval_channel"] == "short_doc_full_text"
    assert docs[0].metadata["file_id"] == "f1"
