"""Node 5: persist document with pipeline metadata."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.services.document_editor_service import DocumentEditorService
from app.services.draft_pipeline.schemas import BlueprintSection, DraftPipelineMetadata, ExtractedFacts
from app.utils.database import ensure_db_session_live

logger = logging.getLogger(__name__)

_SAVE_ATTEMPTS = 3


def _create_with_retry(
    db: Session,
    *,
    case_id: str,
    user_id: str,
    title: str,
    content: str,
    metadata: Dict[str, Any],
):
    last_err: Optional[Exception] = None
    for attempt in range(1, _SAVE_ATTEMPTS + 1):
        try:
            ensure_db_session_live(db)
            svc = DocumentEditorService(db)
            return svc.create_document(
                case_id=case_id,
                user_id=user_id,
                title=title,
                content=content,
                metadata=metadata,
            )
        except OperationalError as exc:
            last_err = exc
            logger.warning("[draft_pipeline.persist] attempt %s failed: %s", attempt, exc)
            ensure_db_session_live(db)
    assert last_err is not None
    raise last_err


def run_persist(
    *,
    db: Session,
    case_id: str,
    user_id: str,
    title: str,
    final_html: str,
    strategy: str,
    template_id: Optional[str],
    template_key: Optional[str],
    template_html: Optional[str],
    facts: ExtractedFacts,
    blueprint: List[BlueprintSection],
    generated_sections: Dict[str, str],
    case_retrieval: Optional[Dict[str, Any]] = None,
    task_plan: Optional[Dict[str, Any]] = None,
    triage: Optional[Dict[str, Any]] = None,
    extraction_records: Optional[List[Dict[str, Any]]] = None,
    generation_mode: str = "unified",
) -> Dict[str, Any]:
    mode = generation_mode if generation_mode in ("unified", "decomposed") else "unified"
    meta = DraftPipelineMetadata(
        pipeline_version="unified_v1" if mode == "unified" else "decomposed_v5",
        generation_mode=mode,  # type: ignore[arg-type]
        strategy=strategy,  # type: ignore[arg-type]
        template_id=template_id,
        template_key=template_key,
        template_html=template_html if strategy == "template" else None,
        document_title=title,
        extracted_facts=facts.to_prompt_json(),
        case_retrieval=dict(case_retrieval or {}),
        task_plan=dict(task_plan or {}),
        triage=dict(triage or {}),
        extraction_records=list(extraction_records or []),
        blueprint=[b.model_dump() for b in blueprint],
        generated_sections=generated_sections,
    )
    doc = _create_with_retry(
        db,
        case_id=case_id,
        user_id=user_id,
        title=title,
        content=final_html,
        metadata=meta.to_document_metadata(),
    )
    preview = (final_html or "")[:500]
    logger.info("[draft_pipeline.persist] document_id=%s title=%s", doc.id, title)
    return {
        "id": str(doc.id),
        "title": doc.title,
        "preview": preview,
    }
