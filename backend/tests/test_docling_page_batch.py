"""Unit tests for page-batched Docling helpers (no real Docling convert)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from app.services.docling_page_batch import (
    PdfPageBatch,
    convert_pdf_in_page_batches,
    extract_pdf_page_range_bytes,
    iter_pdf_page_batches,
    pdf_page_count,
    rebase_segment_pages,
    should_batch_pdf,
)


def _make_pdf_bytes(pages: int) -> bytes:
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page-{i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


@dataclass
class _FakeSeg:
    text: str
    page_no: Optional[int] = None
    prov_items: List[Dict[str, Any]] = field(default_factory=list)


def test_iter_pdf_page_batches_contiguous():
    batches = iter_pdf_page_batches(100, batch_pages=30)
    assert [(b.start, b.end) for b in batches] == [
        (0, 30),
        (30, 60),
        (60, 90),
        (90, 100),
    ]
    assert batches[-1].label == "91-100"


def test_should_batch_pdf_threshold():
    assert should_batch_pdf(total_pages=39, min_pages=40, enabled=True) is False
    assert should_batch_pdf(total_pages=40, min_pages=40, enabled=True) is True
    assert should_batch_pdf(total_pages=500, min_pages=40, enabled=False) is False


def test_pdf_page_count_and_extract_roundtrip():
    pdf = _make_pdf_bytes(7)
    assert pdf_page_count(pdf) == 7
    chunk = extract_pdf_page_range_bytes(pdf, 2, 5)
    assert pdf_page_count(chunk) == 3


def test_rebase_segment_pages_shifts_local_to_absolute():
    segs = [
        _FakeSeg("a", page_no=1, prov_items=[{"page_no": 1}]),
        _FakeSeg("b", page_no=3, prov_items=[{"page_no": 3}]),
    ]
    rebase_segment_pages(segs, page_offset=30)
    assert segs[0].page_no == 31
    assert segs[0].prov_items[0]["page_no"] == 31
    assert segs[1].page_no == 33


def test_convert_pdf_in_page_batches_rebases_and_concatenates():
    pdf = _make_pdf_bytes(5)
    calls: List[str] = []

    def convert_batch(batch_bytes: bytes, batch_name: str):
        calls.append(batch_name)
        n = pdf_page_count(batch_bytes)
        segs = [_FakeSeg(f"t{i}", page_no=i + 1) for i in range(n)]
        return segs, ""

    done: List[PdfPageBatch] = []

    segs, full_text = convert_pdf_in_page_batches(
        pdf_bytes=pdf,
        filename="stmt.pdf",
        batch_pages=2,
        convert_batch=convert_batch,
        on_batch_done=lambda b, i, n: done.append(b),
    )

    assert len(calls) == 3
    assert [s.page_no for s in segs] == [1, 2, 3, 4, 5]
    assert full_text == "t0t1t0t1t0"
    assert len(done) == 3
    assert done[0].start == 0 and done[0].end == 2
    assert done[-1].start == 4 and done[-1].end == 5


def test_extract_invalid_range_raises():
    pdf = _make_pdf_bytes(2)
    with pytest.raises(ValueError):
        extract_pdf_page_range_bytes(pdf, 1, 1)
