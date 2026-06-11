"""Unified case materials retrieval for Draft pipeline (decomposed sub-queries)."""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.services.chat.case_assistant_intent import resolve_case_assistant_intent
from app.services.chat.case_context_pipeline import run_case_context_pipeline
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.evidence_plan import apply_evidence_plan
from app.services.chat.execution_tier import attach_pipeline_budget_for_tier
from app.services.draft_pipeline.schemas import (
    CaseRetrievalSnapshot,
    DocumentTriageResult,
    DraftTaskPlan,
    RetrievalSubQuery,
)
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

_MAX_MERGED_CONTEXT = 48_000
_SNIPPET_MAX = 1400


def _count_case_corpus(db: Session, case_id: str) -> int:
    from app.services.chat.retrieval_router import _count_case_files

    try:
        return int(_count_case_files(db, str(case_id)))
    except Exception:
        return 0


def build_draft_retrieval_budget_profile(
    *,
    user_prompt: str,
    corpus_size: int,
    attached_files_count: int = 0,
) -> Dict[str, Any]:
    intent = resolve_case_assistant_intent(
        question=user_prompt,
        attached_files_count=attached_files_count,
        corpus_size=corpus_size,
        draft_mode=True,
    )
    base = ConversationPolicyService.budget_profile_for_depth(
        depth_tier=intent.depth_tier,
        task_type=intent.task_type,
        corpus_size=corpus_size,
        question=user_prompt,
        clarification_needed=intent.clarification_needed,
        draft_mode=True,
        attached_files_count=attached_files_count,
    )
    profile = attach_pipeline_budget_for_tier(
        base,
        "deep",
        tier_reason="draft_pipeline",
        primary_intent=intent.primary,
        response_shape=intent.response_shape,
        response_shape_reason=intent.reason,
    )
    profile["execution_tier"] = "deep"
    profile["tier_reason"] = "draft_pipeline"
    return apply_evidence_plan(profile, intent=intent)


def _chunk_key(text: str, file_id: str = "") -> str:
    return hashlib.sha256(f"{file_id}:{text[:200]}".encode()).hexdigest()


def _file_ids_for_sub_query(triage: DocumentTriageResult, role: str) -> List[str]:
    if not role or role == "unspecified":
        return triage.all_active_file_ids
    matched = [f.file_id for f in triage.core_files + triage.sidebar_files if f.role == role]
    if matched:
        return matched
    return triage.all_active_file_ids


def retrieve_decomposed_materials(
    *,
    rag_service: RAGService,
    case_id: str,
    user_prompt: str,
    db: Session,
    task_plan: DraftTaskPlan,
    triage: DocumentTriageResult,
    attached_file_ids: Optional[List[str]] = None,
) -> CaseRetrievalSnapshot:
    """
    Execute each decomposed sub-query through case assistant pipeline (scoped to triaged files).
    """
    prompt = (user_prompt or "").strip()
    attached = [str(x) for x in (attached_file_ids or []) if str(x).strip()]
    corpus_size = _count_case_corpus(db, case_id) if db else 0
    budget = build_draft_retrieval_budget_profile(
        user_prompt=prompt,
        corpus_size=corpus_size,
        attached_files_count=len(attached),
    )

    sub_queries: List[RetrievalSubQuery] = list(task_plan.sub_queries or [])
    if not sub_queries:
        sub_queries = [
            RetrievalSubQuery(query_id="q_main", role="", search_query=prompt, purpose="main")
        ]

    merged_parts: List[str] = []
    seen_keys: Set[str] = set()
    scoped_union: Set[str] = set()
    meta_queries: List[Dict[str, Any]] = []
    total_chars = 0

    for sq in sub_queries:
        scope_ids = _file_ids_for_sub_query(triage, sq.role)
        if attached:
            scope_ids = [x for x in scope_ids if x in attached] or attached

        pipeline_out = run_case_context_pipeline(
            rag_service=rag_service,
            case_id=str(case_id),
            question=sq.search_query,
            db=db,
            attached_file_ids=scope_ids or None,
            corpus_size=corpus_size,
            budget_profile=budget,
        )
        ctx = str(pipeline_out.get("rag_context") or "").strip()
        for fid in pipeline_out.get("scoped_file_ids") or scope_ids:
            if fid:
                scoped_union.add(str(fid))

        if ctx:
            key = _chunk_key(ctx, sq.query_id)
            if key not in seen_keys:
                seen_keys.add(key)
                block = f"[Подзапрос: {sq.role or sq.query_id}]\n{ctx[:_SNIPPET_MAX * 3]}"
                if total_chars + len(block) <= _MAX_MERGED_CONTEXT:
                    merged_parts.append(block)
                    total_chars += len(block)

        meta_queries.append(
            {
                "query_id": sq.query_id,
                "role": sq.role,
                "search_query": sq.search_query[:200],
                "scoped_files": len(scope_ids),
                "chars": len(ctx),
            }
        )

    snapshot = CaseRetrievalSnapshot(
        rag_context="\n\n---\n\n".join(merged_parts),
        scoped_file_ids=sorted(scoped_union),
        retrieval_task={"decomposed_sub_queries": meta_queries},
        context_pipeline_meta={
            "pipeline": True,
            "mode": "decomposed_sub_queries",
            "sub_queries_executed": len(sub_queries),
        },
        sub_queries_executed=len(sub_queries),
    )
    logger.info(
        "[draft_pipeline.case_retrieval] decomposed case=%s sub_queries=%s chars=%s files=%s",
        case_id,
        len(sub_queries),
        len(snapshot.rag_context),
        len(snapshot.scoped_file_ids),
    )
    return snapshot


def retrieve_case_materials_for_draft(
    *,
    rag_service: RAGService,
    case_id: str,
    user_prompt: str,
    db: Session,
    attached_file_ids: Optional[List[str]] = None,
    task_plan: Optional[DraftTaskPlan] = None,
    triage: Optional[DocumentTriageResult] = None,
) -> CaseRetrievalSnapshot:
    """Entry point: decomposed retrieval when plan+triage present, else single-pass fallback."""
    if task_plan and triage and (task_plan.sub_queries or task_plan.required_doc_roles):
        return retrieve_decomposed_materials(
            rag_service=rag_service,
            case_id=case_id,
            user_prompt=user_prompt,
            db=db,
            task_plan=task_plan,
            triage=triage,
            attached_file_ids=attached_file_ids,
        )

    prompt = (user_prompt or "").strip()
    attached = [str(x) for x in (attached_file_ids or []) if str(x).strip()]
    corpus_size = _count_case_corpus(db, case_id) if db else 0
    budget = build_draft_retrieval_budget_profile(
        user_prompt=prompt,
        corpus_size=corpus_size,
        attached_files_count=len(attached),
    )
    pipeline_out = run_case_context_pipeline(
        rag_service=rag_service,
        case_id=str(case_id),
        question=prompt,
        db=db,
        attached_file_ids=attached or None,
        corpus_size=corpus_size,
        budget_profile=budget,
    )
    return CaseRetrievalSnapshot.from_pipeline_result(pipeline_out)


def fetch_file_text_for_extraction(
    *,
    rag_service: RAGService,
    case_id: str,
    file_id: str,
    search_query: str,
    db: Session,
    k: int = 8,
) -> str:
    """Isolated chunk retrieval for one file (Layer 2 map step)."""
    try:
        docs = rag_service.retrieve_context(
            case_id=str(case_id),
            query=search_query,
            k=k,
            db=db,
            file_ids=[str(file_id)],
            use_hybrid=True,
            retrieval_strategy="hybrid",
        )
        parts = [(getattr(d, "page_content", None) or "").strip() for d in (docs or [])]
        parts = [p[:1600] for p in parts if p]
        return "\n\n".join(parts)[:12000]
    except Exception as exc:
        logger.warning("[draft_pipeline.case_retrieval] file fetch failed file=%s: %s", file_id, exc)
        return ""


def get_rag_service() -> RAGService:
    return RAGService()
