"""
Attach Docling/OCR bbox geometry to tabular source_references.

Contract:
- Geometry comes only from leaf chunks (micro / row / docling), never macro/preamble.
- One quote → tightest matching leaf chunk → bbox filtered to that quote's char span.
- Micro geometry overwrites a stale/wrong bbox left from a parent chunk.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.services.prov_span_utils import char_spans_overlap, locate_quote_in_original
from app.services.tabular_cell_payload import (
    _clean_text,
    _copy_bbox,
    _copy_page_bbox,
    _quote_in_span,
)

logger = logging.getLogger(__name__)

# Parent blocks are for LLM context, not for pixel highlights.
_GEOMETRY_EXCLUDED_LEVELS = frozenset({"macro", "preamble"})
# Preferred leaf levels when the index is hierarchical.
_GEOMETRY_LEAF_LEVELS = frozenset({"micro", "row", "docling"})


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


def best_doc_for_geometry(
    docs: Sequence[Document],
    *,
    quote: str,
    char_start: Optional[int],
    char_end: Optional[int],
) -> Optional[Document]:
    """
    Pick the tightest leaf chunk that actually contains the quote.

    Never returns macro/preamble. Tie-break: higher score, then smaller char span.
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
            score += 5
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
                    score += 3
                elif char_spans_overlap(mcs_i, mce_i, cs_i, ce_i):
                    score += 1
        except (TypeError, ValueError):
            pass
        if score >= 3:
            ranked.append((score, _chunk_span_len(doc), doc))

    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return ranked[0][2]


def _has_bbox(ref: Dict[str, Any]) -> bool:
    return _copy_bbox(ref.get("bbox")) is not None


def resolve_ref_char_span(
    *,
    ref: Dict[str, Any],
    original_text: str,
) -> tuple[Optional[int], Optional[int]]:
    """Locate quote offsets in the file original_text; fall back to stored span if valid."""
    ref_text = _clean_text(ref.get("text"))
    located = locate_quote_in_original(original_text, ref_text) if original_text and ref_text else None
    if located is not None:
        return located

    try:
        cs = ref.get("char_start")
        ce = ref.get("char_end")
        if cs is not None and ce is not None and int(ce) > int(cs):
            if not original_text or _quote_in_span(original_text, int(cs), int(ce), ref_text):
                return int(cs), int(ce)
    except (TypeError, ValueError):
        pass
    return None, None


def attach_bbox_to_source_reference(
    *,
    ref: Dict[str, Any],
    docs: List[Document],
    original_text: str = "",
) -> Dict[str, Any]:
    """
    Return a copy of ref with bbox/page_bbox from the best leaf chunk.

    If a micro/row match is found, its geometry wins over any pre-existing bbox
    (which may have been stamped from a parent macro).
    """
    from app.services.chat.citation_payload import resolve_citation_page_from_metadata
    from app.services.rag_service import RAGService

    out = dict(ref)
    ref_text = _clean_text(out.get("text"))
    if not ref_text and out.get("char_start") is None:
        return out

    char_start, char_end = resolve_ref_char_span(ref=out, original_text=original_text)
    matched = best_doc_for_geometry(
        docs,
        quote=ref_text,
        char_start=char_start,
        char_end=char_end,
    )
    if matched is None:
        return out

    meta = getattr(matched, "metadata", None) or {}
    page = resolve_citation_page_from_metadata(meta)
    if page is not None:
        out["page"] = page

    if char_start is not None and char_end is not None:
        out["char_start"] = char_start
        out["char_end"] = char_end

    try:
        regions, page_bbox = RAGService._extract_bbox_regions(
            meta,
            char_start=char_start,
            char_end=char_end,
        )
    except Exception:
        logger.debug("bbox extract failed for quote=%r", ref_text[:80], exc_info=True)
        return out

    bbox = _copy_bbox(regions[0]) if regions else None
    pb = _copy_page_bbox(page_bbox)
    if bbox is None:
        return out

    if (
        original_text
        and char_start is not None
        and char_end is not None
        and ref_text
        and not _quote_in_span(original_text, char_start, char_end, ref_text)
    ):
        return out

    out["bbox"] = bbox
    if pb is not None:
        out["page_bbox"] = pb
    elif "page_bbox" in out and _copy_page_bbox(out.get("page_bbox")) is None:
        out.pop("page_bbox", None)
    return out


def enrich_source_references_with_geometry(
    *,
    refs: Optional[List[Any]],
    docs: List[Document],
    original_text: str = "",
) -> List[Dict[str, Any]]:
    """Enrich each source_reference with leaf-chunk bbox (micro wins over macro)."""
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
