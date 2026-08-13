"""Tests for tabular source_reference geometry enrichment."""
from langchain_core.documents import Document

from app.services.tabular_source_geometry import (
    attach_bbox_to_source_reference,
    best_doc_for_geometry,
    enrich_source_references_with_geometry,
    extract_geometry_for_char_span,
    filter_docs_for_geometry,
)


def _doc_with_prov(
    *,
    content: str,
    char_start: int,
    char_end: int,
    chunk_level: str = "micro",
    bbox: dict | None = None,
    page_no: int = 1,
) -> Document:
    box = bbox or {"l": 10.0, "t": 100.0, "r": 200.0, "b": 80.0}
    return Document(
        page_content=content,
        metadata={
            "source_page": page_no,
            "chunk_level": chunk_level,
            "char_start": char_start,
            "char_end": char_end,
            "dl_meta": {
                "page_bbox": {"width": 600.0, "height": 800.0},
                "doc_items": [
                    {
                        "prov": [
                            {
                                "page_no": page_no,
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


def test_best_doc_matches_by_span_without_page_content_hit():
    """Geometry must not require quote text inside chunk.page_content."""
    original = "AAAA " + ("слово " * 20) + "хвост"
    quote = original[5:40]
    qs, qe = 5, 40
    # page_content deliberately does not contain the quote head
    micro = _doc_with_prov(
        content="другие слова без совпадения",
        char_start=0,
        char_end=len(original),
        chunk_level="micro",
        bbox={"l": 20.0, "t": 300.0, "r": 220.0, "b": 280.0},
    )
    # Stamp prov tightly on the quote span
    micro.metadata["dl_meta"]["doc_items"][0]["prov"][0]["char_start"] = qs
    micro.metadata["dl_meta"]["doc_items"][0]["prov"][0]["char_end"] = qe
    picked = best_doc_for_geometry([micro], quote=quote, char_start=qs, char_end=qe)
    assert picked is micro


def test_extract_geometry_unions_overlapping_leaf_boxes():
    original = "первая часть. вторая часть здесь."
    a = _doc_with_prov(
        content="первая часть.",
        char_start=0,
        char_end=13,
        bbox={"l": 10.0, "t": 100.0, "r": 100.0, "b": 80.0},
    )
    b = _doc_with_prov(
        content="вторая часть здесь.",
        char_start=14,
        char_end=len(original),
        bbox={"l": 10.0, "t": 70.0, "r": 120.0, "b": 50.0},
    )
    # Quote spans both leaves
    regions, page_bbox, page = extract_geometry_for_char_span(
        [a, b],
        char_start=0,
        char_end=len(original),
    )
    assert len(regions) == 2
    assert page_bbox == {"width": 600.0, "height": 800.0}
    assert page == 1


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
    assert out["bbox_regions"] == [out["bbox"]]


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


def test_attach_uses_quote_fallback_when_ref_text_missing_from_ocr():
    original = "Объект аренды: электросамокаты моделей Ninebot Max."
    verbatim = "электросамокаты моделей Ninebot Max"
    paraphrased = "электросамокаты Ninebot"
    qs = original.index(verbatim)
    qe = qs + len(verbatim)
    docs = [
        _doc_with_prov(
            content=verbatim,
            char_start=qs,
            char_end=qe,
            bbox={"l": 30.0, "t": 150.0, "r": 300.0, "b": 120.0},
        )
    ]
    # Prov stamped exactly on verbatim span
    docs[0].metadata["dl_meta"]["doc_items"][0]["prov"][0]["char_start"] = qs
    docs[0].metadata["dl_meta"]["doc_items"][0]["prov"][0]["char_end"] = qe

    out = attach_bbox_to_source_reference(
        ref={"text": paraphrased, "page": 1},
        docs=docs,
        original_text=original,
        quote_fallback=verbatim,
    )
    assert out["char_start"] == qs
    assert out["char_end"] == qe
    assert out["bbox"] == {"x0": 30.0, "y0": 120.0, "x1": 300.0, "y1": 150.0}


def test_attach_rejects_whole_document_span_without_locate():
    original = "x" * 500 + " уникальный хвост объекта " + "y" * 500
    docs = [
        _doc_with_prov(
            content=original,
            char_start=0,
            char_end=len(original),
            chunk_level="micro",
        )
    ]
    out = attach_bbox_to_source_reference(
        ref={
            "text": "совсем другой текст которого нет",
            "char_start": 0,
            "char_end": len(original),
            "bbox": {"x0": 1.0, "y0": 1.0, "x1": 10.0, "y1": 10.0},
        },
        docs=docs,
        original_text=original,
    )
    assert out.get("bbox") is None
    assert out.get("char_start") is None


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
