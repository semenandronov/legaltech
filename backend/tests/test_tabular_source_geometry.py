"""Tests for tabular source_reference geometry enrichment."""
from langchain_core.documents import Document

from app.services.tabular_source_geometry import (
    attach_bbox_to_source_reference,
    best_doc_for_geometry,
    enrich_source_references_with_geometry,
    filter_docs_for_geometry,
)


def _doc_with_prov(
    *,
    content: str,
    char_start: int,
    char_end: int,
    chunk_level: str = "micro",
    bbox: dict | None = None,
) -> Document:
    box = bbox or {"l": 10.0, "t": 100.0, "r": 200.0, "b": 80.0}
    return Document(
        page_content=content,
        metadata={
            "source_page": 1,
            "chunk_level": chunk_level,
            "char_start": char_start,
            "char_end": char_end,
            "dl_meta": {
                "page_bbox": {"width": 600.0, "height": 800.0},
                "doc_items": [
                    {
                        "prov": [
                            {
                                "page_no": 1,
                                "char_start": char_start,
                                "char_end": char_end,
                                "bbox": box,
                            }
                        ]
                    }
                ],
            },
        },
    )


def test_filter_docs_for_geometry_drops_macro():
    macro = _doc_with_prov(content="whole page", char_start=0, char_end=200, chunk_level="macro")
    micro = _doc_with_prov(content="clause", char_start=40, char_end=80, chunk_level="micro")
    out = filter_docs_for_geometry([macro, micro])
    assert len(out) == 1
    assert out[0].metadata["chunk_level"] == "micro"


def test_best_doc_for_geometry_prefers_micro_over_macro():
    original = "Шапка договора. 1.1. В соответствии с настоящим Договором Продавец обязуется."
    quote = "1.1. В соответствии с настоящим Договором Продавец обязуется."
    macro = _doc_with_prov(
        content=original,
        char_start=0,
        char_end=len(original),
        chunk_level="macro",
        bbox={"l": 1.0, "t": 700.0, "r": 500.0, "b": 680.0},  # top-of-page
    )
    micro = _doc_with_prov(
        content=quote,
        char_start=original.index(quote),
        char_end=original.index(quote) + len(quote),
        chunk_level="micro",
        bbox={"l": 50.0, "t": 200.0, "r": 400.0, "b": 160.0},  # clause
    )
    picked = best_doc_for_geometry(
        [macro, micro],
        quote=quote,
        char_start=original.index(quote),
        char_end=original.index(quote) + len(quote),
    )
    assert picked is micro


def test_attach_overwrites_stale_macro_bbox_with_micro():
    original = "Шапка договора. 1.1. В соответствии с настоящим Договором Продавец обязуется."
    quote = "1.1. В соответствии с настоящим Договором Продавец обязуется."
    qs = original.index(quote)
    qe = qs + len(quote)
    macro = _doc_with_prov(
        content=original,
        char_start=0,
        char_end=len(original),
        chunk_level="macro",
        bbox={"l": 1.0, "t": 700.0, "r": 500.0, "b": 680.0},
    )
    micro = _doc_with_prov(
        content=quote,
        char_start=qs,
        char_end=qe,
        chunk_level="micro",
        bbox={"l": 50.0, "t": 200.0, "r": 400.0, "b": 160.0},
    )
    ref = {
        "text": quote,
        "page": 1,
        # Stale geometry from parent chunk (top of page).
        "bbox": {"x0": 1.0, "y0": 680.0, "x1": 500.0, "y1": 700.0},
        "page_bbox": {"width": 600.0, "height": 800.0},
    }
    out = attach_bbox_to_source_reference(
        ref=ref,
        docs=[macro, micro],
        original_text=original,
    )
    assert out["bbox"] == {"x0": 50.0, "y0": 160.0, "x1": 400.0, "y1": 200.0}


def test_attach_bbox_from_chunk_prov_for_located_quote():
    original = "ВОЗРАЖЕНИЯ в отношении признания должника банкротом"
    quote = "ВОЗРАЖЕНИЯ в отношении признания должника банкротом"
    docs = [_doc_with_prov(content=original, char_start=0, char_end=len(original))]
    ref = {"text": quote, "page": 1}

    out = attach_bbox_to_source_reference(ref=ref, docs=docs, original_text=original)

    assert out["bbox"] == {"x0": 10.0, "y0": 80.0, "x1": 200.0, "y1": 100.0}
    assert out["page_bbox"] == {"width": 600.0, "height": 800.0}
    assert out["char_start"] == 0
    assert out["char_end"] == len(quote)


def test_enrich_fills_only_missing_geometry():
    original = "первая цитата. вторая цитата здесь."
    docs = [
        _doc_with_prov(content="первая цитата.", char_start=0, char_end=14),
        _doc_with_prov(content="вторая цитата здесь.", char_start=15, char_end=35),
    ]
    refs = [
        {"text": "первая цитата.", "page": 1},
        {
            "text": "вторая цитата здесь.",
            "page": 1,
            "bbox": {"x0": 9.0, "y0": 9.0, "x1": 11.0, "y1": 11.0},
            "page_bbox": {"width": 100.0, "height": 200.0},
        },
    ]
    out = enrich_source_references_with_geometry(
        refs=refs, docs=docs, original_text=original
    )
    assert "bbox" in out[0]
    # Second ref is rewritten from its own micro chunk when resolvable.
    assert out[1]["bbox"] == {"x0": 10.0, "y0": 80.0, "x1": 200.0, "y1": 100.0}
