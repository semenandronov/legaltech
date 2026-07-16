"""Prov span helpers: char-range scoped bbox for chunks and citations."""

from app.services.prov_span_utils import (
    annotate_prov_items_char_span,
    narrow_char_span_to_quote,
    prov_items_for_char_span,
)
from app.services.rag_service import RAGService


def test_prov_items_for_char_span_filters_overlapping_blocks():
    prov_a = [{"page_no": 1, "bbox": {"l": 0, "t": 100, "r": 50, "b": 80}}]
    prov_b = [{"page_no": 1, "bbox": {"l": 0, "t": 200, "r": 50, "b": 180}}]
    spans = [
        (0, 50, annotate_prov_items_char_span(prov_a, 0, 50)),
        (100, 150, annotate_prov_items_char_span(prov_b, 100, 150)),
    ]
    micro = prov_items_for_char_span(spans, 5, 45)
    assert len(micro) == 1
    assert micro[0]["char_start"] == 0


def test_narrow_char_span_to_quote():
    original = "AAA начало работ по договору BBB конец"
    start, end = 4, 35
    hs, he = narrow_char_span_to_quote(
        original=original,
        span_start=start,
        span_end=end,
        quote_anchor="начало работ по договору",
    )
    assert original[hs:he] == "начало работ по договору"


def test_locate_quote_in_original_finds_each_passage():
    from app.services.prov_span_utils import locate_quote_in_original

    original = (
        "Шиошвили возражают против банкротства. "
        "Позже просят ввести реструктуризацию долгов сроком на 6 месяцев."
    )
    a = locate_quote_in_original(original, "Шиошвили возражают против банкротства")
    b = locate_quote_in_original(
        original, "просят ввести реструктуризацию долгов сроком на 6 месяцев"
    )
    assert a is not None and b is not None
    assert a[0] != b[0]
    assert "возражают" in original[a[0] : a[1]]
    assert "реструктуризацию" in original[b[0] : b[1]]


def test_extract_bbox_regions_filters_by_char_span():
    meta = {
        "dl_meta": {
            "page_bbox": {"width": 595.0, "height": 842.0},
            "doc_items": [
                {
                    "prov": [
                        {
                            "page_no": 1,
                            "char_start": 0,
                            "char_end": 50,
                            "bbox": {"l": 10, "t": 800, "r": 100, "b": 780},
                        },
                        {
                            "page_no": 1,
                            "char_start": 100,
                            "char_end": 150,
                            "bbox": {"l": 10, "t": 750, "r": 100, "b": 730},
                        },
                    ]
                }
            ],
        },
    }
    all_regions, _ = RAGService._extract_bbox_regions(meta)
    assert len(all_regions) == 2
    filtered, _ = RAGService._extract_bbox_regions(meta, char_start=5, char_end=45)
    assert len(filtered) == 1
    assert filtered[0]["y0"] == 780.0


def test_extract_bbox_regions_legacy_caps_to_one_when_filtered():
    meta = {
        "dl_meta": {
            "doc_items": [
                {
                    "prov": [
                        {"page_no": 1, "bbox": {"l": 10, "t": 800, "r": 100, "b": 780}},
                        {"page_no": 1, "bbox": {"l": 10, "t": 750, "r": 100, "b": 730}},
                    ]
                }
            ],
        },
    }
    filtered, _ = RAGService._extract_bbox_regions(meta, char_start=0, char_end=200)
    assert len(filtered) == 1
