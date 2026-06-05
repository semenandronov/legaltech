"""Unit tests for citation_payload (Docling offsets + SSE contract)."""

import json

from langchain_core.documents import Document

from app.services.chat.citation_payload import (
    build_retrieval_citations,
    expand_dc_markers_to_cite_zw,
    repair_citation_brackets,
    enrich_structured_citations,
)
from app.services.langchain_agents.utils.reducers import (
    citations_state_reducer,
    merge_citations_reducer,
)
from app.services.chat.events import SSESerializer


def test_build_retrieval_citations_quote_anchor_matches_original_text_nn_joiner():
    # Как в DocumentProcessor.split_documents: два чанка -> original "hello\n\nworld"
    file_id = "f1"
    original = "hello\n\nworld"
    d0 = Document(
        page_content="hello",
        metadata={
            "file_id": file_id,
            "source_file": "a.txt",
            "source_page": 1,
            "char_start": 0,
            "char_end": 5,
            "chunk_id": "c0",
            "chunk_index": 0,
        },
    )
    d1 = Document(
        page_content="world",
        metadata={
            "file_id": file_id,
            "source_file": "a.txt",
            "source_page": 1,
            "char_start": 7,
            "char_end": 12,
            "chunk_id": "c1",
            "chunk_index": 1,
        },
    )
    cites = build_retrieval_citations(
        [d0, d1],
        original_text_by_file_id={file_id: original},
    )
    assert len(cites) == 2
    assert cites[0]["quote_anchor"] == "hello"
    assert cites[1]["quote_anchor"] == "world"
    assert cites[0]["chunk_id"] == "c0"
    assert cites[1]["chunk_id"] == "c1"
    assert cites[0]["retrieval_d"] == 1
    assert cites[0]["retrieval_c"] == 0
    assert cites[1]["retrieval_d"] == 1
    assert cites[1]["retrieval_c"] == 1
    assert cites[0]["text_preview"] == "hello"
    assert cites[1]["text_preview"] == "world"


def test_expand_dc_markers_to_cite_zw():
    d0 = Document(
        page_content="alpha",
        metadata={"file_id": "fa", "source_file": "a.pdf", "chunk_index": 0, "chunk_id": "x0"},
    )
    d1 = Document(
        page_content="beta",
        metadata={"file_id": "fb", "source_file": "b.pdf", "chunk_index": 2, "chunk_id": "x1"},
    )
    cites = build_retrieval_citations([d0, d1])
    raw = "Утверждение один [d1:c0]. Ещё [D2:C2]."
    out, meta = expand_dc_markers_to_cite_zw(raw, cites)
    assert meta["expanded"] == 2
    assert cites[0]["citation_id"] in out
    assert cites[1]["citation_id"] in out
    assert "[D" not in out and "[d" not in out


def test_expand_dc_markers_removes_unknown_pair():
    d0 = Document(page_content="x", metadata={"file_id": "f", "source_file": "a.pdf", "chunk_index": 1})
    cites = build_retrieval_citations([d0])
    out, meta = expand_dc_markers_to_cite_zw("Текст [D9:C9].", cites)
    assert "[D" not in out
    assert meta["removed_invalid_dc"] == 1


def test_build_retrieval_citations_aligns_offsets_when_original_has_extra_whitespace():
    # Legacy mismatch: original_text stored with leading/trailing spaces, but offsets computed on stripped chunk.
    file_id = "f-align"
    original = "  hello  \n\n  world  "
    # Offsets as if chunks were stripped and joined: "hello\n\nworld" -> second starts at 7.
    d1 = Document(
        page_content="world",
        metadata={
            "file_id": file_id,
            "source_file": "a.txt",
            "source_page": 1,
            "char_start": 7,
            "char_end": 12,
            "chunk_id": "c1",
        },
    )
    cites = build_retrieval_citations([d1], original_text_by_file_id={file_id: original})
    assert cites[0]["quote_anchor"].strip() == "world"
    # and corrected offsets should point into original where "world" exists
    assert original[cites[0]["char_start"] : cites[0]["char_end"]].strip() == "world"


def test_build_retrieval_citations_nested_provenance_bbox():
    meta = {
        "file_id": "f3",
        "source_file": "p.pdf",
        "source_page": 1,
        "char_start": 0,
        "char_end": 2,
        "chunk_id": "z2",
        "docling_provenance": {
            "bounding_box": {"x0": 10, "y0": 20, "x1": 30, "y1": 40},
            "page_size": {"width": 200.0, "height": 300.0},
        },
    }
    cites = build_retrieval_citations([Document(page_content="ab", metadata=meta)])
    # STRICT mode: bbox/page_bbox are taken only from Docling dl_meta provenance.
    assert cites[0]["bbox"] is None
    assert cites[0]["page_bbox"] is None


def test_build_retrieval_citations_bbox_aliases():
    meta = {
        "file_id": "f2",
        "source_file": "x.pdf",
        "source_page": 2,
        "char_start": 0,
        "char_end": 3,
        "chunk_id": "z",
        "bounding_box": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
        "page_size": {"width": 595.0, "height": 842.0},
    }
    cites = build_retrieval_citations([Document(page_content="abc", metadata=meta)])
    # STRICT mode: bbox/page_bbox are taken only from Docling dl_meta provenance.
    assert cites[0]["bbox"] is None
    assert cites[0]["page_bbox"] is None


def test_build_retrieval_citations_yandex_bbox_regions():
    """Сканы: bbox из top-level bbox_regions (Yandex OCR), без Docling dl_meta."""
    meta = {
        "file_id": "fscan",
        "source_file": "scan.pdf",
        "source_page": 1,
        "chunk_id": "ych1",
        "char_start": 0,
        "char_end": 10,
        "bbox_regions": [{"x0": 50.0, "y0": 100.0, "x1": 200.0, "y1": 120.0}],
        "page_bbox": {"width": 595.0, "height": 842.0},
    }
    cites = build_retrieval_citations([Document(page_content="текст", metadata=meta)])
    assert cites[0]["bbox"] == {"x0": 50.0, "y0": 100.0, "x1": 200.0, "y1": 120.0}
    assert cites[0]["page_bbox"] == {"width": 595.0, "height": 842.0}
    assert cites[0]["bbox_regions"] == meta["bbox_regions"]


def test_build_retrieval_citations_dl_meta_multiple_prov_regions():
    """Без char span на prov — legacy: в citation не более одного bbox."""
    meta = {
        "file_id": "fpdf",
        "source_file": "doc.pdf",
        "source_page": 1,
        "chunk_id": "ch1",
        "char_start": 0,
        "char_end": 200,
        "dl_meta": {
            "page_bbox": {"width": 595.0, "height": 842.0},
            "doc_items": [
                {
                    "prov": [
                        {"bbox": {"l": 10, "t": 800, "r": 100, "b": 780}},
                        {"bbox": {"l": 10, "t": 750, "r": 100, "b": 730}},
                    ]
                }
            ],
        },
    }
    cites = build_retrieval_citations([Document(page_content="hi", metadata=meta)])
    assert cites[0]["bbox"] == {"x0": 10.0, "y0": 780.0, "x1": 100.0, "y1": 800.0}
    assert cites[0]["page_bbox"] == {"width": 595.0, "height": 842.0}
    regions = cites[0]["bbox_regions"]
    assert len(regions) == 1


def test_build_retrieval_citations_filters_prov_by_char_span():
    meta = {
        "file_id": "fpdf",
        "source_file": "doc.pdf",
        "chunk_id": "ch2",
        "char_start": 0,
        "char_end": 40,
        "dl_meta": {
            "page_bbox": {"width": 595.0, "height": 842.0},
            "doc_items": [
                {
                    "prov": [
                        {
                            "char_start": 0,
                            "char_end": 50,
                            "bbox": {"l": 10, "t": 800, "r": 100, "b": 780},
                        },
                        {
                            "char_start": 60,
                            "char_end": 120,
                            "bbox": {"l": 10, "t": 750, "r": 100, "b": 730},
                        },
                    ]
                }
            ],
        },
    }
    cites = build_retrieval_citations(
        [Document(page_content="x" * 100, metadata=meta)],
        original_text_by_file_id={"fpdf": "x" * 100},
    )
    regions = cites[0]["bbox_regions"]
    assert len(regions) == 1
    assert regions[0]["y0"] == 780.0


def test_repair_citation_brackets():
    t, meta = repair_citation_brackets("Тезис [1] и [99].", 2)
    assert "[1]" in t
    assert "[99]" not in t
    assert meta["removed_invalid"] == 1


def test_repair_normalizes_source_style_brackets():
    t, meta = repair_citation_brackets("Факт [Источник 3, позиция 6434].", 10)
    assert "[3]" in t
    assert "Источник" not in t
    assert meta["normalized_source_style"] == 1


def test_citations_state_reducer_empty_list_clears_stale():
    stale = [{"source_id": "f", "chunk_id": "c1", "page": 1}]
    assert citations_state_reducer(stale, []) == []
    assert citations_state_reducer(stale, None) == stale


def test_merge_citations_reducer_keeps_two_chunks_same_page():
    a = {
        "source_id": "f",
        "file_name": "x.pdf",
        "page": 1,
        "chunk_id": "c1",
        "char_start": 0,
        "char_end": 5,
    }
    b = {
        "source_id": "f",
        "file_name": "x.pdf",
        "page": 1,
        "chunk_id": "c2",
        "char_start": 10,
        "char_end": 20,
    }
    merged = merge_citations_reducer([a], [b])
    assert len(merged) == 2


def test_merge_citations_reducer_later_update_overlays_fields():
    """Тот же chunk_id: поля из второго списка (enrich) не теряются."""
    retrieval = {
        "source_id": "f",
        "file_name": "x.pdf",
        "page": 2,
        "chunk_id": "c1",
        "quote": "short",
    }
    enriched = {
        "source_id": "f",
        "file_name": "x.pdf",
        "page": 2,
        "chunk_id": "c1",
        "quote_anchor": "longer anchor from original",
        "debug_docling_prov_page_nos": [2, 3],
    }
    merged = merge_citations_reducer([retrieval], [enriched])
    assert len(merged) == 1
    assert merged[0]["quote_anchor"] == "longer anchor from original"
    assert merged[0]["debug_docling_prov_page_nos"] == [2, 3]
    assert merged[0]["quote"] == "short"


def test_enrich_structured_maps_file_id_from_docs():
    docs = [
        Document(
            page_content="chunk body",
            metadata={
                "file_id": "real-file-id",
                "doc_id": "internal",
                "chunk_id": "chk-1",
                "source_file": "d.pdf",
                "source_page": 3,
                "char_start": 1,
                "char_end": 4,
            },
        )
    ]
    originals = {"real-file-id": "xchunk bodyy"}
    out = enrich_structured_citations(
        [
            {
                "source_id": "internal",
                "file_name": "d.pdf",
                "page": 3,
                "quote": "chunk",
                "char_start": 1,
                "char_end": 4,
                "chunk_id": "chk-1",
                "bbox": None,
                "page_bbox": None,
            }
        ],
        docs,
        originals,
    )
    assert out[0]["source_id"] == "real-file-id"
    assert (out[0]["quote_anchor"] or "").startswith("chunk body")


def test_sse_serializer_citations_keeps_index_and_debug_docling():
    """Citation.model_fields должен включать index и debug_docling_prov_page_nos для SSE."""
    sse = SSESerializer.citations(
        [
            {
                "source_id": "s1",
                "file_name": "doc.pdf",
                "quote": "x",
                "index": 2,
                "debug_docling_prov_page_nos": [5, 6],
            }
        ]
    )
    json_str = sse.replace("data: ", "").strip()
    data = json.loads(json_str)
    c0 = data["citations"][0]
    assert c0["index"] == 2
    assert c0["debug_docling_prov_page_nos"] == [5, 6]
