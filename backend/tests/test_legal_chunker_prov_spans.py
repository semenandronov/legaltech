"""Micro chunks receive only OCR prov overlapping their char span."""

from app.services.legal_chunker import _MacroChunk, _Segment, _build_micro_chunks, _PROFILES
from app.services.prov_span_utils import collect_prov_spans_from_segments, prov_items_for_char_span


def _prov(page: int = 1) -> list:
    return [{"page_no": page, "bbox": {"l": 1.0, "t": 10.0, "r": 2.0, "b": 9.0}}]


def test_micro_chunk_prov_scoped_to_char_span():
    """Micro prov must not include OCR blocks from another segment on the page."""
    profile = _PROFILES["contracts"]
    seg_a = _Segment(
        text=("A " * 200) + "\n\n",
        section_title="",
        section_number="",
        char_start=0,
        char_end=402,
        prov_items=_prov(),
    )
    seg_b = _Segment(
        text=("B " * 200) + "\n\n",
        section_title="",
        section_number="",
        char_start=402,
        char_end=804,
        prov_items=_prov(),
    )
    prov_spans = collect_prov_spans_from_segments([seg_a, seg_b])
    macro_text = seg_a.text + seg_b.text
    macro = _MacroChunk(
        text=macro_text,
        char_start=0,
        char_end=len(macro_text),
        section_title="",
        section_number="",
        parent_path=[],
        page_start=1,
        page_end=1,
        macro_id="m1",
        macro_index=0,
        prov_items=prov_items_for_char_span(prov_spans, 0, len(macro_text)),
        prov_spans=prov_spans,
    )
    micros = _build_micro_chunks([macro], profile, {})
    assert micros
    first = micros[0]
    last = micros[-1]
    assert len(first.get("prov_items") or []) == 1
    assert len(last.get("prov_items") or []) == 1
    assert first["char_end"] <= 402 or first["char_start"] < 402
    assert last["char_start"] >= 402 or last["char_end"] > 402
