"""Hybrid path: SQL facts from statements + scoped document RAG → one synthesis."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.retrieval_router import RetrievalTask
from app.services.chat.outbound_turn_state import turn_state_from_hybrid_scope
from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline

logger = logging.getLogger(__name__)


def _hybrid_budget(base: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    bp = dict(base) if isinstance(base, dict) else {}
    bp.setdefault("execution_tier", "instant")
    bp["recall_k"] = min(int(bp.get("recall_k") or 24), 24)
    bp["final_k"] = min(int(bp.get("final_k") or 8), 8)
    bp["rerank_enabled"] = True
    bp["rerank_tier"] = "light"
    bp["unified_retrieval"] = True
    return bp


def _synthesize_hybrid_answer(
    *,
    question: str,
    sql_block: str,
    rag_context: str,
) -> str:
    if not (sql_block or "").strip() and not (rag_context or "").strip():
        return "Недостаточно данных для ответа по делу."

    try:
        from app.services.chat.case_query_planner import draft_generation_model_uri
        from app.services.llm_factory import create_llm

        max_tokens = max(
            512,
            int(getattr(config, "STATEMENT_SQL_SYNTHESIS_MAX_TOKENS", 1024) or 1024),
        )
        llm = create_llm(
            model=draft_generation_model_uri(),
            temperature=0.1,
            max_tokens=max_tokens,
            use_rate_limiting=False,
            cache_enabled=False,
        )
        parts: List[str] = []
        if sql_block.strip():
            parts.append(f"=== ДАННЫЕ ВЫПИСКИ (SQL) ===\n{sql_block.strip()}")
        if rag_context.strip():
            parts.append(f"=== ФРАГМЕНТЫ ДОКУМЕНТОВ (RAG) ===\n{rag_context.strip()[:12000]}")
        evidence = "\n\n".join(parts)
        resp = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Ты юридический ассистент. Ответь на вопрос, объединив факты из выписки "
                        "и содержание документов. Не выдумывай суммы и даты. Кратко и по делу."
                    )
                ),
                HumanMessage(
                    content=f"КОНТЕКСТ:\n{evidence}\n\nВОПРОС:\n{question.strip()}"
                ),
            ]
        )
        text = resp.content if hasattr(resp, "content") else str(resp)
        return (text or "").strip() or "Не удалось сформировать ответ."
    except Exception as exc:
        logger.warning("[HybridStructuredAgent] synthesis failed: %s", exc)
        if sql_block.strip():
            return sql_block.strip()
        return (rag_context or "")[:4000].strip() or "Не удалось сформировать ответ."


def run_hybrid_structured_agent(
    db: Session,
    *,
    case_id: str,
    question: str,
    statement_scope_file_ids: Sequence[str],
    rag_file_ids: Sequence[str],
    attached_file_ids: Optional[Sequence[str]] = None,
    budget_profile: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """SQL pipeline + scoped RAG on narrative files, then LLM synthesis."""
    if not db or not case_id or not (question or "").strip():
        return None
    if not statement_scope_file_ids or not rag_file_ids:
        return None

    sql_patch = run_statement_sql_pipeline(
        db,
        case_id=case_id,
        question=question,
        scope_file_ids=list(statement_scope_file_ids),
        attached_file_ids=attached_file_ids or list(statement_scope_file_ids),
    )
    sql_answer = ""
    sql_citations: List[Dict[str, Any]] = []
    if sql_patch:
        sql_answer = str(sql_patch.get("response") or "").strip()
        sql_citations = list(sql_patch.get("citations") or [])

    from app.services.chat.case_context_pipeline import (
        complete_retrieval_after_recall,
        run_hybrid_recall,
    )
    from app.services.rag_service import get_rag_service

    rag_service = get_rag_service()
    hybrid_bp = _hybrid_budget(budget_profile)
    retrieval_task = RetrievalTask(
        search_query=question.strip(),
        file_ids=list(rag_file_ids),
        scope_mode="attached",
        confidence=0.9,
        rationale="structured_data_router_hybrid",
    )
    docs, recall_meta = run_hybrid_recall(
        rag_service=rag_service,
        case_id=case_id,
        question=question,
        db=db,
        retrieval_task=retrieval_task,
        attached_file_ids=list(rag_file_ids),
        budget_profile=hybrid_bp,
    )
    rag_patch = complete_retrieval_after_recall(
        question=question,
        docs=docs,
        case_id=case_id,
        rag_service=rag_service,
        db=db,
        budget_profile=hybrid_bp,
    )
    rag_context = str(rag_patch.get("rag_context") or "").strip()
    rag_citations = list(rag_patch.get("citations") or [])

    if not sql_answer and not rag_context:
        logger.info("[HybridStructuredAgent] no sql or rag context case=%s", case_id)
        return None

    sql_block = sql_answer
    if not sql_block and sql_patch is None:
        sql_block = "[SQL: нет данных по выписке для этого вопроса]"

    answer = _synthesize_hybrid_answer(
        question=question,
        sql_block=sql_block,
        rag_context=rag_context,
    )
    citations = sql_citations + [
        c for c in rag_citations if c not in sql_citations
    ]

    sql_meta = (sql_patch or {}).get("statement_sql_meta") if isinstance(sql_patch, dict) else {}
    sql_op = str((sql_meta or {}).get("operation") or "").strip()
    outbound_turn_state = turn_state_from_hybrid_scope(
        statement_file_ids=statement_scope_file_ids,
        rag_file_ids=rag_file_ids,
        sql_operation=sql_op,
    ).to_dict()

    logger.info(
        "[HybridStructuredAgent] case=%s sql_chars=%s rag_chars=%s recall=%s",
        case_id,
        len(sql_block),
        len(rag_context),
        recall_meta.get("recall_docs") if isinstance(recall_meta, dict) else "?",
    )
    return {
        "transaction_agent_resolved": True,
        "hybrid_agent_resolved": True,
        "structured_data_plane": "hybrid",
        "response": answer,
        "messages": [AIMessage(content=answer)],
        "citations": citations,
        "rag_context": rag_context,
        "rag_documents": rag_patch.get("rag_documents"),
        "context_pipeline_meta": rag_patch.get("context_pipeline_meta"),
        "statement_sql_meta": sql_meta if isinstance(sql_meta, dict) else None,
        "outbound_turn_state": outbound_turn_state,
    }
