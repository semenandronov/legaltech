"""Node: decomposed sub-query retrieval after triage."""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.services.draft_pipeline.case_retrieval import get_rag_service, retrieve_case_materials_for_draft
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot, DocumentTriageResult, DraftTaskPlan

logger = logging.getLogger(__name__)


def run_case_materials_retrieval(
    *,
    db: Session,
    case_id: str,
    user_prompt: str,
    task_plan: DraftTaskPlan,
    triage: DocumentTriageResult,
    attached_file_ids: Optional[List[str]] = None,
) -> CaseRetrievalSnapshot:
    rag_service = get_rag_service()
    return retrieve_case_materials_for_draft(
        rag_service=rag_service,
        case_id=case_id,
        user_prompt=user_prompt,
        db=db,
        attached_file_ids=attached_file_ids,
        task_plan=task_plan,
        triage=triage,
    )
