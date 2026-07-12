"""
Page-batched Docling conversion for large PDFs.

Why: a single converter.convert() on 100–500 page statements OOMs / times out
on typical Yandex VMs (1 Docling slot, limited RAM). Production approach:

  - small PDFs → one-shot convert (unchanged)
  - large PDFs → convert page windows, rebase page_no, concatenate segments
  - release memory between batches
  - report progress via ingest_progress

Downstream (_iter_docling_segments, StructuredTableIndexer) stays unchanged.
"""
from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Callable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfPageBatch:
    """0-based half-open page range [start, end)."""

    start: int
    end: int

    @property
    def page_count(self) -> int:
        return max(0, self.end - self.start)

    @property
    def label(self) -> str:
        if self.page_count <= 0:
            return "empty"
        return f"{self.start + 1}-{self.end}"


def pdf_page_count(pdf_bytes: bytes) -> int:
    """Return page count; 0 if unreadable."""
    try:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return int(len(doc))
        finally:
            doc.close()
    except Exception:
        try:
            import pypdf

            reader = pypdf.PdfReader(BytesIO(pdf_bytes))
            return int(len(reader.pages))
        except Exception as exc:
            logger.debug("[docling_page_batch] page_count failed: %s", exc)
            return 0


def extract_pdf_page_range_bytes(pdf_bytes: bytes, start: int, end: int) -> bytes:
    """
    Extract pages [start, end) as a standalone PDF (0-based).

    Prefers PyMuPDF (same as OCR batching); falls back to pypdf.
    """
    if start < 0 or end <= start:
        raise ValueError(f"invalid page range [{start}, {end})")

    try:
        import fitz

        src = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            total = len(src)
            s = max(0, min(start, total))
            e = max(s, min(end, total))
            if e <= s:
                raise ValueError(f"empty page range after clamp [{start}, {end}) total={total}")
            out = fitz.open()
            try:
                out.insert_pdf(src, from_page=s, to_page=e - 1)
                return out.tobytes()
            finally:
                out.close()
        finally:
            src.close()
    except ImportError:
        pass

    import pypdf

    reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    total = len(reader.pages)
    s = max(0, min(start, total))
    e = max(s, min(end, total))
    if e <= s:
        raise ValueError(f"empty page range after clamp [{start}, {end}) total={total}")
    writer = pypdf.PdfWriter()
    for i in range(s, e):
        writer.add_page(reader.pages[i])
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def iter_pdf_page_batches(
    total_pages: int,
    *,
    batch_pages: int,
) -> List[PdfPageBatch]:
    """Split [0, total_pages) into contiguous batches of at most batch_pages."""
    if total_pages <= 0:
        return []
    size = max(1, int(batch_pages))
    batches: List[PdfPageBatch] = []
    start = 0
    while start < total_pages:
        end = min(start + size, total_pages)
        batches.append(PdfPageBatch(start=start, end=end))
        start = end
    return batches


def should_batch_pdf(
    *,
    total_pages: int,
    min_pages: int,
    enabled: bool,
) -> bool:
    if not enabled:
        return False
    return total_pages >= max(2, int(min_pages))


def rebase_segment_pages(segments: Sequence[Any], *, page_offset: int) -> None:
    """
    Shift Docling local 1-based page numbers to absolute document pages.

    absolute = local + page_offset  (page_offset is 0-based start of batch).
    Mutates segments in place (including nested prov page_no).
    """
    if not page_offset:
        return
    for seg in segments:
        if getattr(seg, "page_no", None) is not None:
            try:
                seg.page_no = int(seg.page_no) + int(page_offset)
            except Exception:
                pass
        prov_items = getattr(seg, "prov_items", None) or []
        for prov in prov_items:
            if isinstance(prov, dict) and prov.get("page_no") is not None:
                try:
                    prov["page_no"] = int(prov["page_no"]) + int(page_offset)
                except Exception:
                    pass


ConvertBatchFn = Callable[[bytes, str], Tuple[List[Any], str]]


def convert_pdf_in_page_batches(
    *,
    pdf_bytes: bytes,
    filename: str,
    batch_pages: int,
    convert_batch: ConvertBatchFn,
    on_batch_done: Optional[Callable[[PdfPageBatch, int, int], None]] = None,
) -> Tuple[List[Any], str]:
    """
    Convert a PDF in page windows and return concatenated segments + full_text.

    convert_batch(batch_bytes, batch_filename) -> (segments, full_text)
    Segments must use Docling-local 1-based page numbers; this function rebases them.
    """
    total = pdf_page_count(pdf_bytes)
    if total <= 0:
        return [], ""

    batches = iter_pdf_page_batches(total, batch_pages=batch_pages)
    if not batches:
        return [], ""

    all_segments: List[Any] = []
    text_parts: List[str] = []

    for bi, batch in enumerate(batches):
        logger.info(
            "[docling_page_batch] %s batch %s/%s pages %s (%s pages)",
            filename,
            bi + 1,
            len(batches),
            batch.label,
            batch.page_count,
        )
        batch_bytes = extract_pdf_page_range_bytes(pdf_bytes, batch.start, batch.end)
        batch_name = f"{filename}#p{batch.label}"
        segments, _batch_text = convert_batch(batch_bytes, batch_name)
        rebase_segment_pages(segments, page_offset=batch.start)
        all_segments.extend(segments)
        # Rebuild text from rebases segments for consistency.
        text_parts.append("".join(getattr(s, "text", "") or "" for s in segments))

        if on_batch_done is not None:
            try:
                on_batch_done(batch, bi + 1, len(batches))
            except Exception:
                pass

        # Help the weak VM reclaim Docling tensors between windows.
        del batch_bytes
        del segments
        gc.collect()

    full_text = "".join(text_parts)
    return all_segments, full_text
