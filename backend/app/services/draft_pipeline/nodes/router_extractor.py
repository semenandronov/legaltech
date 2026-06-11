"""Node 1 (legacy): resolve strategy — superseded by v5 resolve_template + consolidate_state."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.services.draft_pipeline.nodes.fact_passport import extract_case_fact_passport
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot, ExtractedFacts
from app.services.draft_template_context import resolve_draft_template_context

logger = logging.getLogger(__name__)


def _infer_title(user_prompt: str, template_label: Optional[str]) -> str:
    if template_label and len(template_label.strip()) >= 3:
        return template_label.strip()[:200]
    q = (user_prompt or "").strip()
    if len(q) <= 120:
        return q or "Новый документ"
    return q[:120].rstrip(".,;:") + "…"


def run_router_extractor(
    *,
    db: Session,
    case_id: str,
    user_prompt: str,
    template_system_id: Optional[str] = None,
    template_context: Optional[str] = None,
    template_label: Optional[str] = None,
    template_key: Optional[str] = None,
    attached_file_ids: Optional[list] = None,
    case_retrieval: Optional[CaseRetrievalSnapshot] = None,
) -> Tuple[str, Optional[str], str, Optional[str], Optional[str], Optional[str], ExtractedFacts]:
    """
    Returns:
        strategy, resolved_template_id, document_title, template_html,
        template_label, template_key, facts
    """
    tc = (template_context or "").strip()
    tl = template_label
    tkey = template_key
    resolved_id = (template_system_id or "").strip() or None

    if not tc:
        tc, tl, tkey = resolve_draft_template_context(
            db,
            template_system_id=template_system_id,
            user_question=user_prompt,
            auto_match_system_template=True,
        )
        if tkey and not resolved_id:
            if tkey.startswith("bankruptcy:"):
                resolved_id = tkey.split(":", 1)[1]

    strategy = "template" if tc else "scratch"
    title = _infer_title(user_prompt, tl)

    retrieval = case_retrieval or CaseRetrievalSnapshot()
    facts = extract_case_fact_passport(
        user_prompt=user_prompt,
        case_retrieval=retrieval,
    )
    if not facts.document_type and tl:
        facts = facts.model_copy(update={"document_type": tl.strip()[:200]})

    logger.info(
        "[draft_pipeline.router] strategy=%s template_id=%s title=%s doc_type=%s financial=%s",
        strategy,
        resolved_id,
        title[:60],
        (facts.document_type or "-")[:40],
        facts.financial.confidence,
    )
    return strategy, resolved_id, title, tc or None, tl, tkey, facts
