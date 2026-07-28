"""Section retrieval labels for embedding_text / BM25 / FTS."""
from __future__ import annotations

from langchain_core.documents import Document

from app.config import config
from app.services.legal_chunker import (
    LegalChunkerV2,
    _PROFILES,
    _Segment,
    _apply_hidden_embedding_context,
    build_document_retrieval_text,
)
from app.services.bm25_retriever import BM25Retriever


def test_section_label_on_micro_embedding_text(monkeypatch):
    monkeypatch.setattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", False, raising=False)

    chunker = LegalChunkerV2()
    profile = _PROFILES["contracts"]
    text_b = "1. ПРЕДМЕТ ДОГОВОРА\n\n"
    text_c = "1.4. Заказчик гарантирует права на участок.\n\n"
    segments = [
        _Segment(
            text=text_b,
            section_title="1. ПРЕДМЕТ ДОГОВОРА",
            section_number="1",
            parent_path=["1. ПРЕДМЕТ ДОГОВОРА"],
            page_no=1,
            char_start=0,
            char_end=len(text_b),
            is_heading=True,
        ),
        _Segment(
            text=text_c,
            section_title="1.4. Заказчик гарантирует права на участок.",
            section_number="1.4",
            parent_path=["1. ПРЕДМЕТ ДОГОВОРА", "1.4. Заказчик гарантирует права на участок."],
            page_no=1,
            char_start=len(text_b),
            char_end=len(text_b) + len(text_c),
            is_heading=False,
        ),
    ]
    docs = chunker.chunk_from_segments(
        segments=segments,
        full_text="".join(s.text for s in segments),
        preseg_strategy="ocr_markdown_recursive_legal",
        profile=profile,
        base_metadata={"doc_id": "f1", "file_id": "f1", "case_id": "c1"},
        filename="c.pdf",
    )
    micros = [d for d in docs if d.metadata.get("chunk_level") == "micro"]
    assert micros
    # Find the 1.4 body micro (not only the heading-sized leaf).
    body = next(d for d in micros if "1.4." in (d.page_content or ""))
    et = body.metadata.get("embedding_text") or ""
    assert "Раздел документа:" in et
    assert "ПРЕДМЕТ ДОГОВОРА" in et
    assert "1.4." in et
    # Citation surface stays clean.
    assert not (body.page_content or "").startswith("[Контекст")
    assert build_document_retrieval_text(body) == et.strip()


def test_custom_section_embedding_label_wins(monkeypatch):
    monkeypatch.setattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", False, raising=False)
    docs = [
        Document(
            page_content="1.4. Текст пункта",
            metadata={
                "section_title": "1. ПРЕДМЕТ ДОГОВОРА",
                "section_embedding_label": "Предмет: подряд на СМР конструкций",
                "parent_path": ["1. ПРЕДМЕТ ДОГОВОРА"],
                "chunk_level": "micro",
            },
        )
    ]
    _apply_hidden_embedding_context(docs, enabled=True)
    et = docs[0].metadata.get("embedding_text") or ""
    assert "Предмет: подряд на СМР конструкций" in et
    assert docs[0].page_content == "1.4. Текст пункта"


def test_bm25_indexes_embedding_text_section_label(monkeypatch):
    monkeypatch.setattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", False, raising=False)
    docs = [
        Document(
            page_content="1.4. Заказчик гарантирует права на участок.",
            metadata={
                "section_title": "1. ПРЕДМЕТ ДОГОВОРА",
                "parent_path": ["1. ПРЕДМЕТ ДОГОВОРА"],
                "chunk_level": "micro",
                "chunk_id": "m1",
            },
        ),
        Document(
            page_content="14. ЮРИДИЧЕСКИЕ АДРЕСА И РЕКВИЗИТЫ",
            metadata={"section_title": "14. РЕКВИЗИТЫ", "chunk_level": "micro", "chunk_id": "m2"},
        ),
    ]
    _apply_hidden_embedding_context(docs, enabled=True)
    retriever = BM25Retriever()
    if not retriever.available:
        return
    assert retriever.build_index("case-sec-label", docs)
    hits = retriever.retrieve("case-sec-label", "предмет договора", k=2)
    assert hits
    assert "1.4." in (hits[0].page_content or "")


def test_corpus_synonym_hint_still_applied(monkeypatch):
    monkeypatch.setattr(config, "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", True, raising=False)
    docs = [
        Document(
            page_content="текст нормы",
            metadata={
                "instrument_id": "fz-127",
                "instrument_short_name": "ФЗ-127",
                "section_title": "Статья 1",
                "parent_path": [],
            },
        )
    ]
    _apply_hidden_embedding_context(docs, enabled=True)
    et = docs[0].metadata.get("embedding_text") or ""
    assert "оспаривание" in et.lower()
    assert "Раздел документа:" in et or "Документ:" in et
