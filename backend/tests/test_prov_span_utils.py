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


def test_locate_quote_does_not_pad_forty_chars_before_ocr_party():
    """Regression: OCR preamble quotes must not start ~40 chars early (chunk padding)."""
    from app.services.prov_span_utils import locate_quote_in_original, span_faithfully_covers_quote

    original = (
        "Договор аренды № 20/01-2022/1\n\n"
        "г. Москва\n\n"
        "«20» января 2022г.\n\n"
        "Общество с ограниченной ответственностью «СМАРТ СИТИ» (ИНН 9701032688, ОГРН\n"
        "1167746181173) в лице Генерального директора, действующего на\n"
        "основании устава, именуемое в дальнейшем «Арендодатель»"
    )
    quote = (
        "Общество с ограниченной ответственностью «СМАРТ СИТИ» "
        "(ИНН 9701032688, ОГРН 1167746181173)"
    )
    located = locate_quote_in_original(original, quote)
    assert located is not None
    start, end = located
    snippet = original[start:end]
    assert snippet.lstrip().startswith("Общество")
    assert "20/01-2022" not in snippet
    assert "января" not in snippet
    assert span_faithfully_covers_quote(original, start, end, quote)
    # Explicitly reject the historical padded window.
    bad_start = start - 40
    assert bad_start > 0
    assert not span_faithfully_covers_quote(original, bad_start, end, quote)


def test_narrow_char_span_handles_ocr_newlines_in_party_block():
    from app.services.prov_span_utils import narrow_char_span_to_quote

    original = (
        "хвост номера 3-2022/1\n\nг. Москва\n\n"
        "Общество с ограниченной ответственностью «СМАРТ СИТИ» (ИНН 9701032688, ОГРН\n"
        "1167746181173) далее текст"
    )
    quote = (
        "Общество с ограниченной ответственностью «СМАРТ СИТИ» "
        "(ИНН 9701032688, ОГРН 1167746181173)"
    )
    ns, ne = narrow_char_span_to_quote(
        original=original,
        span_start=0,
        span_end=len(original),
        quote_anchor=quote,
    )
    assert original[ns:ne].lstrip().startswith("Общество")
    assert "3-2022/1" not in original[ns:ne]

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
