"""
Attach Docling/OCR bbox geometry to tabular source_references.

Contract (no chunk-guessing):
1. Locate the quote in file ``original_text`` → [char_start, char_end).
2. Collect every leaf-chunk provenance box that overlaps that span.
3. Persist those boxes on the reference (first = ``bbox``, all = ``bbox_regions``).

Macro/preamble parents are never used as the primary geometry pool.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.services.prov_span_utils import (
    char_spans_overlap,
    locate_quote_in_original,
    narrow_char_span_to_quote,
    prov_entries_have_char_spans,
)
from app.services.tabular_cell_payload import (
    _clean_text,
    _copy_bbox,
    _copy_page_bbox,
)

logger = logging.getLogger(__name__)

# Parent blocks are for LLM context, not for pixel highlights.
_GEOMETRY_EXCLUDED_LEVELS = frozenset({"macro", "preamble"})
# Preferred leaf levels when the index is hierarchical.
_GEOMETRY_LEAF_LEVELS = frozenset({"micro", "row", "docling"})

_Region = Dict[str, float]
_PageBBox = Dict[str, float]


def chunk_level(doc: Document) -> str:
    return str((getattr(doc, "metadata", None) or {}).get("chunk_level") or "").strip().lower()


def is_geometry_chunk(doc: Document) -> bool:
    """True for leaf / legacy chunks that may own a highlight bbox."""
    level = chunk_level(doc)
    if not level:
        return True
    if level in _GEOMETRY_EXCLUDED_LEVELS:
        return False
    return True


def filter_docs_for_geometry(docs: Sequence[Document]) -> List[Document]:
    """
    Drop macro/preamble parents from the geometry candidate pool.

    If the file has no chunk_level metadata (legacy index), keep all docs.
    Prefer explicit leaf levels when both leaf and other non-macro levels exist.
    """
    if not docs:
        return []
    has_levels = any(chunk_level(d) for d in docs)
    if not has_levels:
        return list(docs)

    safe = [d for d in docs if is_geometry_chunk(d)]
    if not safe:
        return []

    leaves = [d for d in safe if chunk_level(d) in _GEOMETRY_LEAF_LEVELS]
    return leaves if leaves else safe


def _chunk_span_len(doc: Document) -> int:
    meta = getattr(doc, "metadata", None) or {}
    try:
        cs = int(meta.get("char_start"))
        ce = int(meta.get("char_end"))
        if ce > cs:
            return ce - cs
    except (TypeError, ValueError):
        pass
    return 10**12


def _region_dedupe_key(box: Dict[str, float]) -> Tuple[float, float, float, float]:
    return (
        round(float(box["x0"]), 4),
        round(float(box["y0"]), 4),
        round(float(box["x1"]), 4),
        round(float(box["y1"]), 4),
    )


def extract_geometry_for_char_span(
    docs: Sequence[Document],
    *,
    char_start: int,
    char_end: int,
) -> Tuple[List[_Region], Optional[_PageBBox], Optional[int]]:
    """
    Union of provenance boxes overlapping [char_start, char_end).

    Scans leaf chunks first; if none yield boxes, falls back to the full doc list
    but still span-filters when prov has char offsets (never paints a whole macro).
    """
    from app.services.chat.citation_payload import resolve_citation_page_from_metadata
    from app.services.rag_service import RAGService

    if char_end <= char_start:
        return [], None, None

    leaf_pool = filter_docs_for_geometry(docs)
    pools: List[List[Document]] = [leaf_pool]
    if docs and leaf_pool != list(docs):
        pools.append(list(docs))

    for pool in pools:
        if not pool:
            continue
        regions: List[_Region] = []
        page_bbox: Optional[_PageBBox] = None
        page: Optional[int] = None
        seen: set[Tuple[float, float, float, float]] = set()

        for doc in pool:
            meta = getattr(doc, "metadata", None) or {}
            if not isinstance(meta, dict):
                continue
            try:
                regs, pb = RAGService._extract_bbox_regions(
                    meta,
                    char_start=char_start,
                    char_end=char_end,
                )
            except Exception:
                logger.debug("bbox extract failed for span %s-%s", char_start, char_end, exc_info=True)
                continue
            if not regs:
                continue
            # Without per-prov char spans, _extract_bbox_regions returns the chunk box.
            # Accept only when the chunk fully contains the quote span (legacy indexes).
            if not prov_entries_have_char_spans(meta):
                try:
                    mcs = meta.get("char_start")
                    mce = meta.get("char_end")
                    if mcs is None or mce is None:
                        continue
                    mcs_i, mce_i = int(mcs), int(mce)
                    if not (mcs_i <= char_start and mce_i >= char_end):
                        continue
                except (TypeError, ValueError):
                    continue
            for raw in regs:
                box = _copy_bbox(raw)
                if box is None:
                    continue
                key = _region_dedupe_key(box)
                if key in seen:
                    continue
                seen.add(key)
                regions.append(box)
            if page_bbox is None:
                page_bbox = _copy_page_bbox(pb)
            if page is None:
                page = resolve_citation_page_from_metadata(meta)

        if regions:
            return regions, page_bbox, page

    return [], None, None


def best_doc_for_geometry(
    docs: Sequence[Document],
    *,
    quote: str,
    char_start: Optional[int],
    char_end: Optional[int],
) -> Optional[Document]:
    """
    Pick the tightest leaf chunk that covers the quote span (or contains quote text).

    Prefer char-span containment; text match is a secondary signal.
    Never returns macro/preamble.
    """
    pool = filter_docs_for_geometry(docs)
    if not pool:
        return None

    head = _clean_text(quote).lower()[:48]
    ranked: List[Tuple[int, int, Document]] = []
    for doc in pool:
        meta = getattr(doc, "metadata", None) or {}
        score = 0
        content = (getattr(doc, "page_content", None) or "").lower()
        if head and head in content:
            score += 3
        mcs = meta.get("char_start")
        mce = meta.get("char_end")
        try:
            if (
                char_start is not None
                and char_end is not None
                and mcs is not None
                and mce is not None
            ):
                mcs_i, mce_i = int(mcs), int(mce)
                cs_i, ce_i = int(char_start), int(char_end)
                if mcs_i <= cs_i and mce_i >= ce_i:
                    score += 5
                elif char_spans_overlap(mcs_i, mce_i, cs_i, ce_i):
                    overlap = min(mce_i, ce_i) - max(mcs_i, cs_i)
                    if overlap > 0:
                        score += 2
        except (TypeError, ValueError):
            pass
        # Span containment alone is enough; do not require page_content text match.
        if score >= 2:
            ranked.append((score, _chunk_span_len(doc), doc))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][2]


def _span_is_whole_document(original_text: str, char_start: int, char_end: int) -> bool:
    n = len(original_text or "")
    if n < 400:
        return False
    span = char_end - char_start
    return span >= int(0.85 * n)


def resolve_ref_char_span(
    *,
    ref: Dict[str, Any],
    original_text: str,
    quote_fallback: str = "",
) -> tuple[Optional[int], Optional[int]]:
    """Locate quote offsets in the file original_text; fall back to stored span if faithful."""
    from app.services.prov_span_utils import span_faithfully_covers_quote
    from app.services.tabular_quote_then_answer import resolve_quote_span_in_original

    candidates: List[str] = []
    for raw in (_clean_text(ref.get("text")), _clean_text(quote_fallback)):
        if raw and raw not in candidates:
            candidates.append(raw)

    for ref_text in candidates:
        if not original_text or not ref_text:
            continue
        located = locate_quote_in_original(original_text, ref_text)
        if located is not None:
            return located
        # Production snap: near-quotes (one-word paraphrase) → contiguous OCR span.
        snapped = resolve_quote_span_in_original(ref_text, original_text)
        if snapped is not None:
            return snapped

    ref_text = candidates[0] if candidates else ""
    try:
        cs = ref.get("char_start")
        ce = ref.get("char_end")
        if cs is not None and ce is not None and int(ce) > int(cs):
            cs_i, ce_i = int(cs), int(ce)
            if original_text and _span_is_whole_document(original_text, cs_i, ce_i):
                # Whole-doc spans are never a precise highlight target.
                if ref_text:
                    ns, ne = narrow_char_span_to_quote(
                        original=original_text,
                        span_start=cs_i,
                        span_end=ce_i,
                        quote_anchor=ref_text,
                    )
                    if span_faithfully_covers_quote(original_text, ns, ne, ref_text):
                        return ns, ne
                    snapped = resolve_quote_span_in_original(ref_text, original_text)
                    if snapped is not None:
                        return snapped
                return None, None
            if not original_text or span_faithfully_covers_quote(
                original_text, cs_i, ce_i, ref_text
            ):
                return cs_i, ce_i
            ns, ne = narrow_char_span_to_quote(
                original=original_text,
                span_start=cs_i,
                span_end=ce_i,
                quote_anchor=ref_text,
            )
            if span_faithfully_covers_quote(original_text, ns, ne, ref_text):
                return ns, ne
            snapped = resolve_quote_span_in_original(ref_text, original_text)
            if snapped is not None:
                return snapped
    except (TypeError, ValueError):
        pass
    return None, None


def attach_bbox_to_source_reference(
    *,
    ref: Dict[str, Any],
    docs: List[Document],
    original_text: str = "",
    quote_fallback: str = "",
) -> Dict[str, Any]:
    """
    Return a copy of ref with quote-accurate char spans and span-filtered bbox.

    Geometry is resolved by quote → char span → overlapping provenance boxes,
    not by picking a single "best" chunk first.
    """
    out = dict(ref)
    ref_text = _clean_text(out.get("text"))
    if not ref_text and not _clean_text(quote_fallback) and out.get("char_start") is None:
        return out

    char_start, char_end = resolve_ref_char_span(
        ref=out,
        original_text=original_text,
        quote_fallback=quote_fallback,
    )
    if char_start is not None and char_end is not None:
        out["char_start"] = char_start
        out["char_end"] = char_end
        # Persist the OCR slice, not the model near-quote.
        if original_text and 0 <= char_start < char_end <= len(original_text):
            ocr_quote = original_text[char_start:char_end].strip()
            if ocr_quote:
                out["text"] = ocr_quote[:500]

    if char_start is None or char_end is None or char_end <= char_start:
        # Cannot place pixels without a located span — drop stale boxes/spans.
        out.pop("char_start", None)
        out.pop("char_end", None)
        out.pop("bbox", None)
        out.pop("bbox_regions", None)
        out.pop("page_bbox", None)
        return out

    regions, page_bbox, page = extract_geometry_for_char_span(
        docs,
        char_start=char_start,
        char_end=char_end,
    )
    if page is not None:
        out["page"] = page

    if not regions:
        # Relocated span without boxes: clear stale parent geometry.
        out.pop("bbox", None)
        out.pop("bbox_regions", None)
        out.pop("page_bbox", None)
        return out

    out["bbox"] = regions[0]
    out["bbox_regions"] = regions
    if page_bbox is not None:
        out["page_bbox"] = page_bbox
    elif "page_bbox" in out and _copy_page_bbox(out.get("page_bbox")) is None:
        out.pop("page_bbox", None)
    return out


def enrich_source_references_with_geometry(
    *,
    refs: Optional[List[Any]],
    docs: List[Document],
    original_text: str = "",
    quote_fallback: str = "",
) -> List[Dict[str, Any]]:
    """Enrich each source_reference: locate quote → span-filtered bbox regions."""
    if not refs:
        return []
    out: List[Dict[str, Any]] = []
    for raw in refs:
        if not isinstance(raw, dict):
            continue
        if not docs:
            out.append(dict(raw))
            continue
        out.append(
            attach_bbox_to_source_reference(
                ref=raw,
                docs=docs,
                original_text=original_text,
                quote_fallback=quote_fallback,
            )
        )
    return out


def load_file_chunk_docs(*, case_id: str, file_id: str) -> List[Document]:
    """Load indexed chunks for a file (empty list on failure)."""
    if not case_id or not file_id:
        return []
    try:
        from app.services.document_processor import get_document_processor

        store = get_document_processor().vector_store
        return store.list_chunks_by_file(str(case_id), str(file_id)) or []
    except Exception:
        logger.debug(
            "load_file_chunk_docs failed case=%s file=%s",
            case_id,
            file_id,
            exc_info=True,
        )
        return []
