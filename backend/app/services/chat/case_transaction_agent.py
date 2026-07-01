"""Case chat agent — statement SQL pipeline + SQL-only ReAct fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.config import config
from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    feature_enabled,
)
from app.services.chat.file_scoped_agent import run_file_scoped_agent
from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline

logger = logging.getLogger(__name__)


def _agent_enabled() -> bool:
    return feature_enabled() and bool(getattr(config, "CASE_TRANSACTION_AGENT_ENABLED", True))


def _resolve_scope_ids(
    db: Session,
    case_id: str,
    *,
    statement_scope_file_ids: Optional[Sequence[str]],
    attached_file_ids: Optional[Sequence[str]],
) -> List[str]:
    tx_ids = set(CaseFileTransactionService.list_transaction_file_ids(db, case_id))
    if statement_scope_file_ids:
        return [str(fid).strip() for fid in statement_scope_file_ids if str(fid).strip() in tx_ids]
    if attached_file_ids:
        return [fid for fid in attached_file_ids if fid in tx_ids]
    return CaseFileTransactionService.list_transaction_file_ids(db, case_id)


def _patch_from_file_scoped_agent(
    db: Session,
    case_id: str,
    agent_result,
) -> Dict[str, Any]:
    citations: List[Dict[str, Any]] = []
    if agent_result.transaction_rows:
        from app.services.chat.case_transaction_graph import build_transaction_citations

        citations = build_transaction_citations(db, case_id, agent_result.transaction_rows)

    return {
        "transaction_agent_resolved": True,
        "response": agent_result.answer,
        "messages": [AIMessage(content=agent_result.answer)],
        "citations": citations,
        "rag_context": "",
    }


def run_case_transaction_agent(
    db: Session,
    *,
    case_id: str,
    question: str,
    attached_file_ids: Optional[Sequence[str]] = None,
    statement_scope_file_ids: Optional[Sequence[str]] = None,
    sql_plan_hints: Optional[dict] = None,
    prior_turn_state: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """
    1. Statement SQL pipeline (planner → executor) — primary for count/sum/list/find.
    2. SQL-only ReAct fallback when planner cannot build a plan.

    Sets transaction_agent_resolved when SQL path succeeds (no RAG fallback).
    """
    if not _agent_enabled() or not db or not case_id or not (question or "").strip():
        return None

    scope_ids = _resolve_scope_ids(
        db,
        case_id,
        statement_scope_file_ids=statement_scope_file_ids,
        attached_file_ids=attached_file_ids,
    )
    if not scope_ids:
        return None

    pipeline_patch = run_statement_sql_pipeline(
        db,
        case_id=case_id,
        question=question,
        scope_file_ids=scope_ids,
        attached_file_ids=attached_file_ids or scope_ids,
        sql_plan_hints=sql_plan_hints,
        prior_turn_state=prior_turn_state,
    )
    if pipeline_patch:
        return pipeline_patch

    from app.services.rag_service import get_rag_service

    agent_result = run_file_scoped_agent(
        db,
        case_id=case_id,
        question=question,
        file_ids=scope_ids,
        rag_service=get_rag_service(),
        mode="chat",
        sql_only=True,
    )
    if not agent_result or not agent_result.tools_called:
        return None

    if not agent_result.answer:
        logger.warning(
            "[CaseTransactionAgent] SQL tools called but no answer case=%s — skip RAG",
            case_id,
        )
        return None

    logger.info(
        "[CaseTransactionAgent] react_sql_fallback case=%s sql=%s",
        case_id,
        agent_result.sql_tools_called,
    )
    return _patch_from_file_scoped_agent(db, case_id, agent_result)
