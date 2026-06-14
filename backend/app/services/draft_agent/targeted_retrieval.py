"""Bounded targeted RAG for fact gaps."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.config import config
from app.services.draft_agent.tools._emit import emit_tool_completed, emit_tool_started
from app.services.draft_agent.tools.build import TOOL_CASE_SEARCH
from app.services.draft_pipeline.schemas import CaseRetrievalSnapshot
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

_SNIPPET_MAX = 1200
_CONTEXT_APPEND_MAX = 16_000


def _max_gaps_per_round() -> int:
    return int(getattr(config, "DRAFT_COVERAGE_MAX_GAPS_PER_ROUND", 3) or 3)


def _rag_k() -> int:
    return int(getattr(config, "DRAFT_COVERAGE_RETRY_RAG_K", 6) or 6)


def run_targeted_gap_retrieval(
    *,
    db: Session,
    case_id: str,
    gaps: List[Dict[str, Any]],
    existing: CaseRetrievalSnapshot,
    attached_file_ids: Optional[List[str]] = None,
) -> CaseRetrievalSnapshot:
    """
    Execute focused RAG queries for coverage gaps and append to shared context.
    """
    if not gaps:
        return existing

    rag = RAGService()
    scope = [str(x) for x in (attached_file_ids or []) if str(x).strip()] or None
    appended_blocks: List[str] = []
    executed = 0

    for gap in gaps[: _max_gaps_per_round()]:
        if not isinstance(gap, dict):
            continue
        query = str(gap.get("suggested_query") or gap.get("label") or "").strip()
        if not query:
            continue

        emit_tool_started(TOOL_CASE_SEARCH, {"query": query[:160], "k": _rag_k(), "reason": "coverage_retry"})
        try:
            docs = rag.retrieve_context(
                case_id=case_id,
                query=query,
                k=_rag_k(),
                retrieval_strategy="multi_query",
                db=db,
                use_hybrid=True,
                file_ids=scope,
            )
            hits = 0
            for doc in docs or []:
                text = (doc.page_content or "").strip()
                if not text:
                    continue
                meta = doc.metadata or {}
                source = str(meta.get("source_file") or meta.get("source") or "Документ")
                snippet = text[:_SNIPPET_MAX]
                appended_blocks.append(f"[{source}]\n{snippet}")
                hits += 1
            emit_tool_completed(
                TOOL_CASE_SEARCH,
                success=hits > 0,
                output_summary=f"Дособор «{gap.get('label', query)[:60]}»: {hits} фрагм.",
            )
            executed += 1
        except Exception as exc:
            logger.warning("[draft_agent.targeted_retrieval] query failed: %s", exc)
            emit_tool_completed(TOOL_CASE_SEARCH, success=False, output_summary=str(exc)[:300])

    if not appended_blocks:
        return existing

    extra = "\n\n---\n\n".join(appended_blocks)
    if len(extra) > _CONTEXT_APPEND_MAX:
        extra = extra[:_CONTEXT_APPEND_MAX] + "\n…"

    merged_context = (existing.rag_context or "").strip()
    if merged_context:
        merged_context = f"{merged_context}\n\n--- ДОСОБОР ПО ПРОБЕЛАМ ---\n\n{extra}"
    else:
        merged_context = extra

    logger.info(
        "[draft_agent.targeted_retrieval] executed=%s appended_chars=%s",
        executed,
        len(extra),
    )
    return existing.model_copy(
        update={
            "rag_context": merged_context,
            "sub_queries_executed": int(existing.sub_queries_executed or 0) + executed,
        }
    )
