"""Resolve template/scratch strategy and document title (no fact extraction)."""
from __future__ import annotations

import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.services.draft_pipeline.schemas import DraftTaskPlan, ExtractedFacts
from app.services.draft_template_context import resolve_draft_template_context

logger = logging.getLogger(__name__)


def _facts_summary_for_template_pick(facts: ExtractedFacts) -> str:
    """Short context for LLM template router (not full JSON)."""
    parts: list[str] = []
    if facts.document_type:
        parts.append(f"document_type={facts.document_type}")
    if facts.parties:
        parts.append("parties: " + ", ".join(f"{k}={v}" for k, v in list(facts.parties.items())[:4]))
    if facts.amounts:
        parts.append("amounts: " + ", ".join(f"{k}={v}" for k, v in list(facts.amounts.items())[:4]))
    if facts.financial.total_to_claim:
        parts.append(f"total_to_claim={facts.financial.total_to_claim}")
    return "; ".join(parts)[:1200]


def _infer_title(user_prompt: str, template_label: Optional[str], task_plan: DraftTaskPlan) -> str:
    if template_label and len(template_label.strip()) >= 3:
        return template_label.strip()[:200]
    if task_plan.target_document_type:
        return task_plan.target_document_type[:200]
    q = (user_prompt or "").strip()
    if len(q) <= 120:
        return q or "Новый документ"
    return q[:120].rstrip(".,;:") + "…"


def resolve_template_strategy(
    *,
    db: Session,
    user_prompt: str,
    facts: ExtractedFacts,
    task_plan: DraftTaskPlan,
    template_system_id: Optional[str] = None,
    template_context: Optional[str] = None,
    template_label: Optional[str] = None,
    template_key: Optional[str] = None,
) -> Tuple[str, Optional[str], str, Optional[str], Optional[str], Optional[str], ExtractedFacts]:
    tc = (template_context or "").strip()
    tl = template_label
    tkey = template_key
    resolved_id = (template_system_id or "").strip() or None

    if not tc:
        tc, tl, tkey = resolve_draft_template_context(
            db,
            user_question=user_prompt,
            auto_match_system_template=True,
            document_type_hint=facts.document_type or (task_plan.target_document_type or ""),
            facts_summary=_facts_summary_for_template_pick(facts),
        )
        if tkey and not resolved_id and tkey.startswith("bankruptcy:"):
            resolved_id = tkey.split(":", 1)[1]

    strategy = "template" if tc else "scratch"
    title = _infer_title(user_prompt, tl, task_plan)

    if not facts.document_type:
        if task_plan.target_document_type:
            facts = facts.model_copy(update={"document_type": task_plan.target_document_type})
        elif tl:
            facts = facts.model_copy(update={"document_type": tl.strip()[:200]})

    logger.info(
        "[draft_pipeline.resolve_template] strategy=%s title=%s doc_type=%s",
        strategy,
        title[:60],
        (facts.document_type or "-")[:40],
    )
    return strategy, resolved_id, title, tc or None, tl, tkey, facts
