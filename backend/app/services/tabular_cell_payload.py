"""
Build TabularCell DB/API payload with provenance enrichment (CITATION_CONTRACT_V1).

Keeps persistence mapping out of TabularReviewService so the same builder
can be reused from LangGraph nodes and tests.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.models.case import File
from app.models.tabular_review import TabularCell, TabularColumn
from app.services.prov_span_utils import char_spans_overlap, locate_quote_in_original
from app.services.tabular_extraction_policy import (
    is_na_cell_value,
    tabular_confidence_auto_complete_threshold,
    tabular_confidence_review_threshold,
)
from app.services.tabular_cell_verification import CellVerificationOutcome
from app.services.tabular_review_models import TabularCellExtractionModel


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _copy_bbox(value: Any) -> Optional[Dict[str, float]]:
    if not isinstance(value, dict):
        return None
    required = ("x0", "y0", "x1", "y1")
    try:
        bbox = {key: float(value[key]) for key in required}
    except (KeyError, TypeError, ValueError):
        return None
    if bbox["x1"] <= bbox["x0"] or bbox["y1"] <= bbox["y0"]:
        return None
    return bbox


def _copy_page_bbox(value: Any) -> Optional[Dict[str, float]]:
    if not isinstance(value, dict):
        return None
    required = ("width", "height")
    try:
        page_bbox = {key: float(value[key]) for key in required}
    except (KeyError, TypeError, ValueError):
        return None
    if page_bbox["width"] <= 0 or page_bbox["height"] <= 0:
        return None
    return page_bbox


def _reference_identity(ref: Dict[str, Any]) -> Tuple[Any, ...]:
    bbox = _copy_bbox(ref.get("bbox")) or {}
    return (
        ref.get("doc_id"),
        ref.get("page"),
        ref.get("section"),
        _clean_text(ref.get("text")).lower(),
        ref.get("char_start"),
        ref.get("char_end"),
        bbox.get("x0"),
        bbox.get("y0"),
        bbox.get("x1"),
        bbox.get("y1"),
    )


def _quote_in_span(original: str, start: Optional[int], end: Optional[int], quote: str) -> bool:
    if start is None or end is None or end <= start or not original or not quote:
        return False
    snippet = original[int(start) : int(end)].lower()
    head = _clean_text(quote).lower()[:40]
    return bool(head) and head in snippet


def _best_doc_for_quote(
    docs: List[Document],
    *,
    quote: str,
    char_start: Optional[int],
    char_end: Optional[int],
) -> Optional[Document]:
    if not docs:
        return None
    head = _clean_text(quote).lower()[:48]
    ranked: List[Tuple[int, Document]] = []
    for doc in docs:
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
                # Strong: chunk span fully covers the located quote.
                if mcs_i <= cs_i and mce_i >= ce_i:
                    score += 3
                elif char_spans_overlap(mcs_i, mce_i, cs_i, ce_i):
                    # Weak overlap alone is not enough to attach geometry.
                    score += 1
        except (TypeError, ValueError):
            pass
        # Geometry is only safe when the quote text is in the chunk,
        # or the chunk span fully contains the located offsets.
        if score >= 3:
            ranked.append((score, doc))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _build_source_references(
    *,
    result: TabularCellExtractionModel,
    primary_source_doc_id: Optional[str],
    primary_source_char_start: Optional[int],
    primary_source_char_end: Optional[int],
    verified_flag: Optional[bool],
    source_page: Optional[int],
    source_section: Optional[str],
    bbox_regions: List[Dict[str, float]],
    page_bbox: Optional[Dict[str, float]],
    anchor_text: str,
    original_text: str = "",
    included_docs: Optional[List[Document]] = None,
) -> List[Dict[str, Any]]:
    from app.services.chat.citation_payload import resolve_citation_page_from_metadata
    from app.services.rag_service import RAGService

    text_fallback = _clean_text(result.verbatim_extract or anchor_text or result.cell_value)[:240]
    base_refs: List[Dict[str, Any]] = []

    if result.source_references:
        for raw_ref in result.source_references or []:
            if not isinstance(raw_ref, dict):
                continue
            base_refs.append(dict(raw_ref))

    if not base_refs and (source_page is not None or source_section or bbox_regions):
        base_refs = [{}]

    docs = included_docs or []
    primary_bbox = _copy_bbox(bbox_regions[0]) if bbox_regions else None
    refs: List[Dict[str, Any]] = []

    for raw_ref in base_refs:
        ref: Dict[str, Any] = dict(raw_ref)
        ref_text = _clean_text(ref.get("text")) or text_fallback
        if not ref_text:
            continue

        located = locate_quote_in_original(original_text, ref_text) if original_text else None
        char_start: Optional[int] = None
        char_end: Optional[int] = None
        if located is not None:
            char_start, char_end = located
        else:
            # Keep model/chunk offsets only when they actually cover this quote.
            try:
                cs = ref.get("char_start", None)
                ce = ref.get("char_end", None)
                if cs is not None and ce is not None and int(ce) > int(cs):
                    if _quote_in_span(original_text, int(cs), int(ce), ref_text):
                        char_start, char_end = int(cs), int(ce)
            except (TypeError, ValueError):
                pass
            if (
                char_start is None
                and primary_source_char_start is not None
                and primary_source_char_end is not None
                and _quote_in_span(
                    original_text,
                    primary_source_char_start,
                    primary_source_char_end,
                    ref_text,
                )
            ):
                char_start = primary_source_char_start
                char_end = primary_source_char_end

        matched_doc = _best_doc_for_quote(
            docs,
            quote=ref_text,
            char_start=char_start,
            char_end=char_end,
        )
        matched_meta = (getattr(matched_doc, "metadata", None) or {}) if matched_doc else {}

        page = ref.get("page")
        matched_page = resolve_citation_page_from_metadata(matched_meta) if matched_meta else None
        if matched_page is not None:
            page = matched_page
        elif page is None:
            page = source_page

        bbox = _copy_bbox(ref.get("bbox"))
        ref_page_bbox = _copy_page_bbox(ref.get("page_bbox"))
        if bbox is None and matched_meta and char_start is not None and char_end is not None:
            try:
                regions, matched_page_bbox = RAGService._extract_bbox_regions(
                    matched_meta,
                    char_start=char_start,
                    char_end=char_end,
                )
                if regions:
                    bbox = _copy_bbox(regions[0])
                    ref_page_bbox = _copy_page_bbox(matched_page_bbox) or ref_page_bbox
            except Exception:
                pass

        # Drop model/chunk geometry that does not cover this quote's located span.
        if bbox is not None and original_text and char_start is not None and char_end is not None:
            if not _quote_in_span(original_text, char_start, char_end, ref_text):
                bbox = None
                ref_page_bbox = None
        # If we never located the quote, do not keep an untrusted bbox from index/top-chunk.
        if bbox is not None and located is None and not matched_meta:
            bbox = None
            ref_page_bbox = None

        is_anchor_ref = _clean_text(ref_text).lower() == _clean_text(anchor_text).lower()
        merged: Dict[str, Any] = {
            "page": page,
            "section": ref.get("section", source_section),
            "text": ref_text,
            "doc_id": ref.get("doc_id", primary_source_doc_id),
            "char_start": char_start,
            "char_end": char_end,
            "verified": ref.get(
                "verified",
                verified_flag if is_anchor_ref else (True if located is not None else None),
            ),
        }
        if bbox is not None:
            merged["bbox"] = bbox
            if ref_page_bbox is not None:
                merged["page_bbox"] = ref_page_bbox
        elif primary_bbox is not None and is_anchor_ref and located is not None and matched_meta:
            # Anchor may reuse the already-filtered primary geometry when the
            # matched chunk is the same top evidence document.
            merged["bbox"] = primary_bbox
            if page_bbox is not None:
                merged["page_bbox"] = page_bbox

        refs.append(merged)

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for ref in refs:
        key = _reference_identity(ref)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)

    return deduped


def build_tabular_cell_db_payload(
    *,
    file: File,
    column: TabularColumn,
    result: TabularCellExtractionModel,
    included_docs: Optional[List[Document]] = None,
    db: Optional[Session] = None,
    verification_outcome: Optional[CellVerificationOutcome] = None,
) -> Dict[str, Any]:
    """
    Map extraction model → persisted cell dict with status gates and deep links.
    """
    from app.services.chat.citation_payload import resolve_citation_page_from_metadata
    from app.services.prov_span_utils import narrow_char_span_to_quote
    from app.services.rag_service import RAGService
    from app.services.tabular_review_verifier import TabularReviewVerifier

    verifier_result = None
    if db is not None:
        verifier = TabularReviewVerifier(db)
        temp_cell = TabularCell(
            cell_value=result.cell_value,
            normalized_value=result.normalized_value,
            verbatim_extract=result.verbatim_extract,
            confidence_score=result.confidence,
            status="completed",
        )
        verifier_result = verifier.verify_cell(temp_cell, column, file)

    if is_na_cell_value(result.cell_value):
        cell_status = "empty" if not (result.cell_value or "").strip() else "n_a"
    elif verification_outcome and verification_outcome.forced_na:
        cell_status = "n_a"
    elif verification_outcome and verification_outcome.needs_review:
        cell_status = "pending"
    elif verifier_result and not verifier_result.is_valid:
        cell_status = verifier_result.suggested_status
        if cell_status == "completed" and result.confidence < tabular_confidence_review_threshold():
            cell_status = "pending"
    else:
        cell_status = "completed"

    included_docs = included_docs or []
    top_doc = included_docs[0] if included_docs else None
    top_meta: Dict[str, Any] = (getattr(top_doc, "metadata", None) or {}) if top_doc else {}
    original_text = file.original_text or ""

    anchor_text = (result.verbatim_extract or "").strip()
    if not anchor_text and result.source_references and isinstance(result.source_references, list):
        for ref in result.source_references:
            if isinstance(ref, dict):
                anchor_text = str(ref.get("text") or "").strip()
                if anchor_text:
                    break
    if not anchor_text:
        anchor_text = str(result.cell_value or "").strip()

    primary_source_doc_id: Optional[str] = file.id
    primary_source_char_start: Optional[int] = None
    primary_source_char_end: Optional[int] = None
    verified_flag: Optional[bool] = None

    located_anchor = locate_quote_in_original(original_text, anchor_text) if anchor_text else None
    if located_anchor is not None:
        primary_source_char_start, primary_source_char_end = located_anchor
        verified_flag = True
    else:
        raw_cs = top_meta.get("char_start")
        raw_ce = top_meta.get("char_end")
        try:
            if raw_cs is not None and raw_ce is not None:
                cs_i = int(raw_cs)
                ce_i = int(raw_ce)
                if ce_i > cs_i:
                    primary_source_char_start = cs_i
                    primary_source_char_end = ce_i
        except (TypeError, ValueError):
            primary_source_char_start = None
            primary_source_char_end = None

        if (
            primary_source_char_start is not None
            and primary_source_char_end is not None
            and original_text
            and anchor_text
        ):
            try:
                ns, ne = narrow_char_span_to_quote(
                    original=original_text,
                    span_start=int(primary_source_char_start),
                    span_end=int(primary_source_char_end),
                    quote_anchor=anchor_text,
                )
                if int(ne) > int(ns):
                    primary_source_char_start = int(ns)
                    primary_source_char_end = int(ne)
                    snippet = original_text[primary_source_char_start:primary_source_char_end]
                    anchor_clean = anchor_text.strip().lower().replace("…", "").replace("...", "")
                    if anchor_clean and anchor_clean in snippet.lower():
                        verified_flag = True
                    else:
                        verified_flag = False
            except Exception:
                pass

    strict_page: Optional[int] = None
    try:
        if primary_source_char_start is not None and primary_source_char_end is not None:
            matched = _best_doc_for_quote(
                included_docs,
                quote=anchor_text,
                char_start=primary_source_char_start,
                char_end=primary_source_char_end,
            )
            if matched is not None:
                strict_page = resolve_citation_page_from_metadata(
                    getattr(matched, "metadata", None) or {}
                )
        if strict_page is None:
            strict_page = resolve_citation_page_from_metadata(top_meta)
    except Exception:
        strict_page = None

    source_page = strict_page if strict_page is not None else result.source_page
    source_section = result.source_section

    bbox_regions: List[Dict[str, float]] = []
    page_bbox: Optional[Dict[str, float]] = None
    try:
        bbox_meta = top_meta
        matched_for_bbox = _best_doc_for_quote(
            included_docs,
            quote=anchor_text,
            char_start=primary_source_char_start,
            char_end=primary_source_char_end,
        )
        if matched_for_bbox is not None:
            bbox_meta = getattr(matched_for_bbox, "metadata", None) or top_meta
        bbox_regions, page_bbox = RAGService._extract_bbox_regions(
            bbox_meta,
            char_start=primary_source_char_start,
            char_end=primary_source_char_end,
        )
    except Exception:
        bbox_regions, page_bbox = [], None

    source_references = _build_source_references(
        result=result,
        primary_source_doc_id=primary_source_doc_id,
        primary_source_char_start=primary_source_char_start,
        primary_source_char_end=primary_source_char_end,
        verified_flag=verified_flag,
        source_page=source_page,
        source_section=source_section,
        bbox_regions=bbox_regions[:1],
        page_bbox=page_bbox if isinstance(page_bbox, dict) else None,
        anchor_text=anchor_text,
        original_text=original_text,
        included_docs=included_docs,
    )

    if source_references:
        first = source_references[0]
        if first.get("page") is not None:
            source_page = first.get("page")
        if first.get("char_start") is not None and first.get("char_end") is not None:
            primary_source_char_start = first.get("char_start")
            primary_source_char_end = first.get("char_end")

    if (
        not is_na_cell_value(result.cell_value)
        and len(source_references) == 0
        and cell_status == "completed"
    ):
        cell_status = "pending"

    if (
        result.confidence < tabular_confidence_auto_complete_threshold()
        and cell_status == "completed"
    ):
        cell_status = "pending"

    return {
        "file_id": file.id,
        "column_id": column.id,
        "cell_value": result.cell_value,
        "normalized_value": result.normalized_value,
        "verbatim_extract": result.verbatim_extract,
        "source_page": source_page,
        "source_section": source_section,
        "source_references": source_references,
        "reasoning": result.reasoning,
        "confidence_score": float(result.confidence),
        "extraction_method": result.extraction_method,
        "status": cell_status,
        "candidates": None,
        "primary_source_doc_id": primary_source_doc_id,
        "primary_source_char_start": primary_source_char_start,
        "primary_source_char_end": primary_source_char_end,
        "verified_flag": verified_flag,
    }
