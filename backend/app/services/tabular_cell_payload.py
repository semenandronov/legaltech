"""
Build TabularCell DB/API payload with provenance enrichment (CITATION_CONTRACT_V1).

Keeps persistence mapping out of TabularReviewService so the same builder
can be reused from LangGraph nodes and tests.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.models.case import File
from app.models.tabular_review import TabularCell, TabularColumn
from app.services.tabular_extraction_policy import (
    is_na_cell_value,
    tabular_confidence_auto_complete_threshold,
    tabular_confidence_review_threshold,
)
from app.services.tabular_cell_verification import CellVerificationOutcome
from app.services.tabular_review_models import TabularCellExtractionModel


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
        and (file.original_text or "").strip()
        and anchor_text
    ):
        try:
            ns, ne = narrow_char_span_to_quote(
                original=file.original_text or "",
                span_start=int(primary_source_char_start),
                span_end=int(primary_source_char_end),
                quote_anchor=anchor_text,
            )
            if int(ne) > int(ns):
                primary_source_char_start = int(ns)
                primary_source_char_end = int(ne)
                snippet = (file.original_text or "")[primary_source_char_start:primary_source_char_end]
                anchor_clean = anchor_text.strip().lower().replace("…", "").replace("...", "")
                if anchor_clean and anchor_clean in snippet.lower():
                    verified_flag = True
                else:
                    verified_flag = False
        except Exception:
            pass

    strict_page: Optional[int] = None
    try:
        strict_page = resolve_citation_page_from_metadata(top_meta)
    except Exception:
        strict_page = None

    source_page = strict_page if strict_page is not None else result.source_page
    source_section = result.source_section

    bbox_regions: List[Dict[str, float]] = []
    page_bbox: Optional[Dict[str, float]] = None
    try:
        bbox_regions, page_bbox = RAGService._extract_bbox_regions(
            top_meta,
            char_start=primary_source_char_start,
            char_end=primary_source_char_end,
        )
    except Exception:
        bbox_regions, page_bbox = [], None

    source_references: List[Dict[str, Any]] = []
    if source_page or source_section or (bbox_regions and page_bbox):
        regions_to_emit = bbox_regions[:3] if bbox_regions else [None]
        for region in regions_to_emit:
            ref: Dict[str, Any] = {
                "page": source_page,
                "section": source_section,
                "text": (result.verbatim_extract or anchor_text or result.cell_value or "")[:240],
                "doc_id": primary_source_doc_id,
                "char_start": primary_source_char_start,
                "char_end": primary_source_char_end,
                "verified": verified_flag,
            }
            if region and isinstance(region, dict):
                ref["bbox"] = region
                if page_bbox and isinstance(page_bbox, dict):
                    ref["page_bbox"] = page_bbox
            source_references.append(ref)

    if result.source_references:
        for r in result.source_references or []:
            if isinstance(r, dict):
                source_references.append(r)

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
