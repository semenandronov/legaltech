"""File.original_text must index the same coordinate space as chunk char_start/char_end."""

from __future__ import annotations

from langchain_core.documents import Document

from app.services.file_char_basis import (
    CHAR_BASIS_LEGAL_CHUNKER,
    CHAR_BASIS_LOADER_JOIN,
    CHAR_BASIS_STRUCTURED_ROW,
    attach_char_basis,
    docling_direct_char_basis,
    peel_char_basis,
    resolve_ingest_original_text,
)
from app.services.legal_chunker import (
    LegalChunkerV2,
    _PROFILES,
    _Segment,
    _yandex_loader_documents_segmentation,
)


def test_attach_peel_roundtrip():
    docs = [
        Document(page_content="hello", metadata={"chunk_level": "micro", "char_start": 0, "char_end": 5}),
    ]
    attached = attach_char_basis(docs, "hello world basis", CHAR_BASIS_LEGAL_CHUNKER)
    assert len(attached) == 2
    real, text, name = peel_char_basis(attached)
    assert len(real) == 1
    assert text == "hello world basis"
    assert name == CHAR_BASIS_LEGAL_CHUNKER
    assert real[0].metadata.get("char_basis") == CHAR_BASIS_LEGAL_CHUNKER


def test_docling_direct_basis_matches_offsets():
    pages = [
        Document(page_content="  page one  ", metadata={}),
        Document(page_content="page two", metadata={}),
    ]
    basis = docling_direct_char_basis(pages)
    assert basis == "page one\n\npage two"
    # Same contract as DocumentProcessor docling-direct-v1.
    offset = 0
    for part in ("page one", "page two"):
        assert basis[offset : offset + len(part)] == part
        offset += len(part) + 2


def test_resolve_prefers_structured_over_carrier():
    row = Document(
        page_content="Дата: 01.01.2024\nСумма: 10",
        metadata={
            "chunk_level": "row",
            "index_profile": "structured_table",
            "preseg_strategy": "xlsx_openpyxl_grid",
            "char_start": 0,
            "char_end": 1,
        },
    )
    docs = attach_char_basis([row], "SHOULD_NOT_WIN", CHAR_BASIS_LEGAL_CHUNKER)
    out_docs, text, basis = resolve_ingest_original_text(docs, loader_text="loader")
    assert basis == CHAR_BASIS_STRUCTURED_ROW
    assert "Дата: 01.01.2024" in text
    assert "SHOULD_NOT_WIN" not in text
    assert int(out_docs[0].metadata["char_start"]) == 0
    assert text[0 : int(out_docs[0].metadata["char_end"])] == out_docs[0].page_content


def test_resolve_uses_legal_chunker_carrier_when_not_structured():
    micro = Document(
        page_content="4.1. Гарантийный срок товара 6 месяцев.\n",
        metadata={
            "chunk_level": "micro",
            "char_start": 10,
            "char_end": 49,
        },
    )
    # Simulate loader join that drifted (extra spaces) vs cleaned basis.
    loader = "xx\n\n  4.1. Гарантийный срок товара 6 месяцев.  \n\nyy"
    basis_text = "xx\n\n4.1. Гарантийный срок товара 6 месяцев.\nyy"
    docs = attach_char_basis([micro], basis_text, CHAR_BASIS_LEGAL_CHUNKER)
    out_docs, text, basis = resolve_ingest_original_text(docs, loader_text=loader)
    assert basis == CHAR_BASIS_LEGAL_CHUNKER
    assert text == basis_text
    assert text != loader
    assert out_docs[0].metadata.get("char_basis") == CHAR_BASIS_LEGAL_CHUNKER


def test_resolve_falls_back_to_loader_join():
    docs = [Document(page_content="x", metadata={"chunk_level": "micro"})]
    out, text, basis = resolve_ingest_original_text(docs, loader_text="loader text")
    assert basis == CHAR_BASIS_LOADER_JOIN
    assert text == "loader text"
    assert len(out) == 1


def test_ocr_loader_segmentation_basis_matches_micro_offsets():
    """Hybrid/OCR path: page join ≠ block join; original_text must use block join."""
    loader_docs = [
        Document(
            page_content="1. ПРЕДМЕТ\n\n1.1. Работы.\n\n",
            metadata={
                "source_page": 0,
                "ocr": True,
                "yandex_blocks": [
                    {"text": "1. ПРЕДМЕТ", "layout_type": "TITLE", "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1}},
                    {"text": "1.1. Работы.", "layout_type": "TEXT", "bbox": {"x0": 0, "y0": 1, "x1": 1, "y1": 2}},
                ],
            },
        ),
        Document(
            page_content="4.1. Гарантийный срок товара 6 месяцев.",
            metadata={
                "source_page": 1,
                "ocr": True,
                "yandex_blocks": [
                    {
                        "text": "4.1. Гарантийный срок товара 6 месяцев.",
                        "layout_type": "TEXT",
                        "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                    },
                ],
            },
        ),
    ]
    segments, full_text = _yandex_loader_documents_segmentation(loader_docs)
    assert "4.1. Гарантийный срок товара 6 месяцев." in full_text
    # Loader-style join (what used to be stored as original_text) diverges.
    loader_join = "\n\n".join(d.page_content for d in loader_docs)
    assert full_text != loader_join

    chunker = LegalChunkerV2()
    docs = chunker.chunk_from_segments(
        segments=segments,
        full_text=full_text,
        preseg_strategy="ocr_markdown_recursive_legal",
        profile=_PROFILES["contracts"],
        base_metadata={"doc_id": "f", "file_id": "f", "case_id": "c"},
        filename="hybrid.pdf",
    )
    real, basis, name = peel_char_basis(docs)
    assert name == CHAR_BASIS_LEGAL_CHUNKER
    assert basis == full_text

    gold = next(
        d
        for d in real
        if d.metadata.get("chunk_level") == "micro"
        and "4.1. Гарантийный срок товара" in (d.page_content or "")
    )
    cs = int(gold.metadata["char_start"])
    ce = int(gold.metadata["char_end"])
    assert basis[cs:ce] == gold.page_content
    # Old bug: slicing loader_join at chunk offsets misses 4.1.
    assert "4.1. Гарантийный срок товара" not in loader_join[cs:ce] or loader_join[cs:ce] != gold.page_content

    _, citation_text, char_basis = resolve_ingest_original_text(docs, loader_text=loader_join)
    assert char_basis == CHAR_BASIS_LEGAL_CHUNKER
    assert citation_text[cs:ce] == gold.page_content


def test_macro_trailing_newline_still_indexes_into_basis():
    profile = _PROFILES["contracts"]
    text_a = "1. РАЗДЕЛ\n\n"
    text_b = "1.1. Пункт один.\n\n"
    segments = [
        _Segment(
            text=text_a,
            section_title="1. РАЗДЕЛ",
            section_number="1",
            parent_path=["1. РАЗДЕЛ"],
            page_no=1,
            char_start=0,
            char_end=len(text_a),
            is_heading=True,
        ),
        _Segment(
            text=text_b,
            section_title="1.1. Пункт один.",
            section_number="1.1",
            parent_path=["1. РАЗДЕЛ", "1.1. Пункт один."],
            page_no=1,
            char_start=len(text_a),
            char_end=len(text_a) + len(text_b),
            is_heading=False,
        ),
    ]
    full = "".join(s.text for s in segments)
    docs = LegalChunkerV2().chunk_from_segments(
        segments=segments,
        full_text=full,
        preseg_strategy="ocr_markdown_recursive_legal",
        profile=profile,
        base_metadata={"doc_id": "f", "file_id": "f"},
        filename="t.pdf",
    )
    real, basis, _ = peel_char_basis(docs)
    for d in real:
        cs = int(d.metadata["char_start"])
        ce = int(d.metadata["char_end"])
        slice_ = basis[cs:ce]
        # page_content may normalize trailing newlines vs the raw basis slice.
        assert (d.page_content or "").strip() in slice_ or slice_.strip() in (d.page_content or "")
