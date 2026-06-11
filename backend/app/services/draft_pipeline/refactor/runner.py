"""Run section-targeted refactor for draft documents in the editor."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.document_editor_service import DocumentEditorService
from app.services.draft_pipeline.nodes.compiler import compile_scratch_document, compile_template_document
from app.services.draft_pipeline.refactor.refactor_section import refactor_section_text
from app.services.draft_pipeline.refactor.targeter import target_section_id
from app.services.draft_pipeline.schemas import BlueprintSection, DraftPipelineMetadata

logger = logging.getLogger(__name__)


def execute_draft_refactor(
    *,
    db: Session,
    case_id: str,
    user_id: str,
    document_id: str,
    user_prompt: str,
    document_context: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]], Optional[str]]:
    """
    Refactor one section of a draft document created by decomposed pipeline.

    Returns:
        (success, response_message, updated_document_card_or_none, final_html_or_none)
    """
    svc = DocumentEditorService(db)
    doc = svc.get_document(document_id, user_id)
    if not doc:
        return False, "❌ Документ не найден", None, None

    meta = DraftPipelineMetadata.from_document_metadata(doc.document_metadata)
    if not meta or not meta.blueprint:
        return False, "", None, None  # signal: not a draft_pipeline document

    blueprint = [BlueprintSection.model_validate(x) for x in meta.blueprint]
    generated = dict(meta.generated_sections or {})

    sid = target_section_id(
        user_prompt=user_prompt,
        blueprint=blueprint,
        document_context=document_context or doc.content or "",
    )
    if not sid:
        return False, "❌ Не удалось определить раздел для правки", None, None

    spec = next((s for s in blueprint if s.section_id == sid), None)
    if not spec:
        return False, "❌ Раздел не найден в плане документа", None, None

    current = generated.get(sid) or ""
    if not current.strip():
        # Bootstrap from live document if sections weren't stored
        current = f"<section><h2>{spec.title}</h2><p>(из текущего документа)</p></section>"

    new_section = refactor_section_text(
        section_title=spec.title,
        current_section_html=current,
        user_prompt=user_prompt,
        document_context=document_context or doc.content or "",
    )
    generated[sid] = new_section

    template_html = meta.template_html or ""
    if meta.strategy == "template" and template_html.strip():
        final_html = compile_template_document(template_html, blueprint, generated)
    else:
        final_html = compile_scratch_document(blueprint, generated)

    meta.generated_sections = generated
    updated = svc.update_document(
        document_id=document_id,
        user_id=user_id,
        content=final_html,
        metadata=meta.to_document_metadata(),
        create_version=True,
    )
    card = {"id": str(updated.id), "title": updated.title, "preview": final_html[:500]}
    msg = f'✅ Раздел «{spec.title}» обновлён.'
    logger.info("[draft_pipeline.refactor] document_id=%s section=%s", document_id, sid)
    return True, msg, card, final_html
