"""Docling pre-segmentation runs only when content_bytes are passed to LegalChunkerV2."""

from __future__ import annotations

from app.services.legal_chunker import LegalChunkerV2, _Segment


def _fake_docling_segment(content_bytes, filename, ext, *, do_ocr=True):
    assert content_bytes
    seg = _Segment(
        text="Раздел 1\n\nТекст абзаца для теста.\n\n",
        section_title="Раздел 1",
        section_number="1",
        parent_path=[],
        page_no=1,
        char_start=0,
        char_end=40,
        prov_items=[{"page_no": 1, "bbox": {"l": 1, "t": 2, "r": 3, "b": 4}}],
    )
    return [seg], seg.text


def test_chunk_skips_docling_when_content_bytes_missing(monkeypatch):
    calls: list[int] = []

    def _boom(*args, **kwargs):
        calls.append(1)
        return [], ""

    monkeypatch.setattr("app.services.legal_chunker._docling_pre_segmentation", _boom)
    chunker = LegalChunkerV2()
    docs = chunker.chunk(
        content_bytes=None,
        filename="test.pdf",
        base_metadata={"file_id": "f1"},
        fallback_text="Раздел 1\n\n" + ("Текст абзаца. " * 20),
        loader_native_text=True,
    )
    assert calls == []
    assert docs
    assert docs[0].metadata.get("preseg_strategy") == "text_recursive_legal"
    assert not docs[0].metadata.get("dl_meta")


def test_chunk_skips_docling_when_loader_did_ocr_even_with_content_bytes(monkeypatch):
    calls: list[int] = []

    def _boom(*args, **kwargs):
        calls.append(1)
        return [], ""

    monkeypatch.setattr("app.services.legal_chunker._docling_pre_segmentation", _boom)
    chunker = LegalChunkerV2()
    docs = chunker.chunk(
        content_bytes=b"%PDF-1.4 fake",
        filename="scan.pdf",
        base_metadata={"file_id": "f1"},
        fallback_text="# Страница 1\n\n" + ("Текст со скана. " * 20),
        loader_did_ocr=True,
        loader_native_text=False,
        loader_documents=None,
    )
    assert calls == []
    assert docs
    assert str(docs[0].metadata.get("preseg_strategy") or "").startswith("ocr_")


def test_chunk_uses_docling_when_content_bytes_present(monkeypatch):
    monkeypatch.setattr(
        "app.services.legal_chunker._docling_pre_segmentation",
        _fake_docling_segment,
    )
    chunker = LegalChunkerV2()
    docs = chunker.chunk(
        content_bytes=b"%PDF-1.4 fake",
        filename="test.pdf",
        base_metadata={"file_id": "f1"},
        fallback_text="fallback",
        loader_native_text=True,
    )
    assert docs
    assert docs[0].metadata.get("preseg_strategy") == "docling_ast_native_text"
    assert any(d.metadata.get("dl_meta") for d in docs)
