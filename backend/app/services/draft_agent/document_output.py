"""Produce draft HTML: catalog placeholder fill or scratch writer."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.draft_agent.session import DraftAgentSession
from app.services.draft_agent.writer import write_draft_document_html
from app.services.draft_execute_service import execute_catalog_field_fill
from app.services.draft_pipeline.markers import find_gap_markers, gap_marker
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)


def _infer_title(
    *,
    document_title: Optional[str],
    template_label: Optional[str],
    document_instruction: str,
) -> str:
    explicit = (document_title or "").strip()
    if explicit:
        return explicit[:255]
    if template_label and len(template_label.strip()) >= 3:
        return template_label.strip()[:255]
    for line in (document_instruction or "").splitlines():
        line = line.strip()
        if line and len(line) >= 5:
            return line[:255]
    return "Новый документ"


def produce_draft_html(
    db: Session,
    *,
    session: DraftAgentSession,
    document_instruction: str,
    document_title: Optional[str] = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Returns (title, html, meta).

    catalog_fill: deterministic field fill via execute_catalog_field_fill.
    scratch: full writer LLM pass.
    """
    tmpl = session.template
    instruction = (document_instruction or "").strip()
    if not instruction:
        raise ValueError("document_instruction is required")

    if tmpl.mode == "catalog_fill" and tmpl.catalog:
        catalog = tmpl.catalog
        rag = RAGService()
        html, stats = execute_catalog_field_fill(
            rag_service=rag,
            case_id=session.ctx.case_id,
            catalog=catalog,
            db=db,
            attached_file_ids=list(session.ctx.file_ids) or None,
            user_context=instruction,
            template_label=tmpl.template_label or "",
        )
        gaps = find_gap_markers(html)
        unfilled_markers = [m for m in tmpl.placeholders if m in html]
        meta: Dict[str, Any] = {
            "fill_mode": "catalog_fill",
            "template_key": tmpl.template_key,
            "template_label": tmpl.template_label,
            "fields_total": stats.get("fields_total", tmpl.field_count),
            "fields_filled": stats.get("fields_filled"),
            "fields_missing": stats.get("fields_missing"),
            "gap_marker_count": len(gaps),
            "unfilled_placeholders": unfilled_markers[:20],
        }
        meta.update(stats)
        if unfilled_markers:
            for marker in unfilled_markers:
                inner = marker.strip("[]").strip() or "данные"
                html = html.replace(marker, gap_marker(inner), 1)
            meta["unfilled_resolved_with_gaps"] = len(unfilled_markers)

        title = _infer_title(
            document_title=document_title,
            template_label=tmpl.template_label,
            document_instruction=instruction,
        )
        logger.info(
            "[draft_agent.document_output] catalog_fill case=%s filled=%s/%s gaps=%s",
            session.ctx.case_id,
            meta.get("fields_filled"),
            meta.get("fields_total"),
            meta.get("gap_marker_count"),
        )
        return title, html, meta

    if tmpl.mode == "template_guide" and tmpl.template_html:
        financial_claim = bool(
            tmpl.brief_intent and tmpl.brief_intent.requires_financial_calc
        )
        html = write_draft_document_html(
            document_instruction=instruction,
            template_html=tmpl.template_html,
            template_label=tmpl.template_label,
            structure_guide=True,
            financial_claim=financial_claim,
        )
        title = _infer_title(
            document_title=document_title,
            template_label=tmpl.template_label,
            document_instruction=instruction,
        )
        logger.info(
            "[draft_agent.document_output] template_guide case=%s label=%s",
            session.ctx.case_id,
            tmpl.template_label,
        )
        return title, html, {
            "fill_mode": "template_guide",
            "template_key": tmpl.template_key,
            "template_label": tmpl.template_label,
        }

    html = write_draft_document_html(
        document_instruction=instruction,
        template_html=None,
        template_label=None,
    )
    title = _infer_title(
        document_title=document_title,
        template_label=None,
        document_instruction=instruction,
    )
    return title, html, {"fill_mode": "scratch"}
