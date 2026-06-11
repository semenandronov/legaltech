"""Build draft Case State using internal assistant context + optional calculator."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.services.chat.draft_financial_agent import run_draft_financial_calculator_agent
from app.services.draft_pipeline.nodes.consolidate_state import consolidate_extractions
from app.services.draft_pipeline.nodes.document_triage import triage_case_documents
from app.services.draft_pipeline.nodes.parallel_extract import run_parallel_extraction
from app.services.draft_pipeline.nodes.task_decomposer import decompose_draft_task
from app.services.draft_pipeline.schemas import (
    CaseRetrievalSnapshot,
    DocumentTriageResult,
    DraftTaskPlan,
    ExtractedFacts,
)

logger = logging.getLogger(__name__)


def _snapshot_from_assistant_rag(
    *,
    rag_context: str,
    scoped_file_ids: Optional[List[str]],
    citations: Optional[List[Dict[str, Any]]],
) -> CaseRetrievalSnapshot:
    ctx = (rag_context or "").strip()
    file_ids = list(scoped_file_ids or [])
    if not file_ids and citations:
        seen = set()
        for c in citations:
            if not isinstance(c, dict):
                continue
            fid = str(c.get("file_id") or c.get("doc_id") or "").strip()
            if fid and fid not in seen:
                seen.add(fid)
                file_ids.append(fid)
    return CaseRetrievalSnapshot(
        rag_context=ctx[:48000],
        scoped_file_ids=file_ids,
        citations=[c for c in (citations or []) if isinstance(c, dict)][:50],
        context_pipeline_meta={"source": "internal_assistant"},
    )


def build_draft_case_state(
    *,
    db: Session,
    case_id: str,
    user_prompt: str,
    attached_file_ids: Optional[List[str]] = None,
    rag_context: Optional[str] = None,
    scoped_file_ids: Optional[List[str]] = None,
    citations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Layer 1–2 case state for draft, reusing assistant retrieval output when present.

    Returns dict with task_plan, triage, case_retrieval, extraction_records,
    extracted_facts, financial_calculator_meta.
    """
    plan = decompose_draft_task(user_prompt)
    triage = triage_case_documents(
        db=db,
        case_id=str(case_id),
        task_plan=plan,
        attached_file_ids=attached_file_ids,
    )
    records = run_parallel_extraction(
        db=db,
        case_id=str(case_id),
        task_plan=plan,
        triage=triage,
    )
    facts = consolidate_extractions(
        records=records,
        task_plan=plan,
        user_prompt=user_prompt,
    )

    facts, calc_meta = run_draft_financial_calculator_agent(
        user_prompt=user_prompt,
        facts=facts,
        rag_context=rag_context or "",
        task_plan=plan,
    )

    snapshot = _snapshot_from_assistant_rag(
        rag_context=rag_context or "",
        scoped_file_ids=scoped_file_ids,
        citations=citations,
    )

    logger.info(
        "[draft.case_state_builder] case=%s extractions=%s calc_tool=%s calc_applied=%s",
        case_id,
        len(records),
        calc_meta.get("tool_called"),
        calc_meta.get("applied"),
    )

    return {
        "task_plan": plan.to_state_dict(),
        "triage": triage.to_state_dict(),
        "case_retrieval": snapshot.to_state_dict(),
        "extraction_records": [r.model_dump() for r in records],
        "extracted_facts": facts.to_prompt_json(),
        "financial_calculator_meta": calc_meta,
    }


def prebuilt_pipeline_input_from_assistant(
    assistant_state: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Map chat graph state → draft pipeline bootstrap payload."""
    facts_raw = assistant_state.get("extracted_facts")
    records = assistant_state.get("extraction_records")
    if not facts_raw or not records:
        return None
    return {
        "task_plan": assistant_state.get("task_plan") or {},
        "triage": assistant_state.get("triage") or {},
        "case_retrieval": assistant_state.get("case_retrieval") or {},
        "extraction_records": records,
        "extracted_facts": facts_raw,
        "financial_calculator_meta": assistant_state.get("financial_calculator_meta") or {},
        "_from_internal_assistant": True,
    }
