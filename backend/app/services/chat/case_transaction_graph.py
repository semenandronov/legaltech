"""ChatGraph integration for structured-table transaction agent."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case import File as FileModel
from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.case_transaction_agent import run_case_transaction_agent

logger = logging.getLogger(__name__)


def build_transaction_citations(
    db: Session,
    case_id: str,
    rows: Sequence[CaseFileTransaction],
) -> List[Dict[str, Any]]:
    citations: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, 1):
        file_row = db.query(FileModel).filter(FileModel.id == row.file_id).first()
        label = file_row.filename if file_row and file_row.filename else row.file_id
        quote = (row.description or row.operation_datetime_text or "").strip()
        if row.amount_raw:
            quote = f"{row.amount_raw} — {quote}".strip(" —")
        citations.append(
            {
                "label": f"T{idx}",
                "source_type": "document",
                "source_id": row.file_id,
                "file_id": row.file_id,
                "file_name": label,
                "filename": label,
                "page": row.page_start,
                "quote": quote[:500],
                "case_id": case_id,
            }
        )
    return citations


def case_transaction_agent_node(
    state: Dict[str, Any],
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Run tool-calling agent when the case has ingested statement rows."""
    if db is None:
        return {}
    bp = state.get("budget_profile") if isinstance(state.get("budget_profile"), dict) else {}
    exec_contract = bp.get("execution_contract") if isinstance(bp.get("execution_contract"), dict) else {}
    question = str(
        exec_contract.get("effective_query")
        or bp.get("effective_query")
        or bp.get("resolved_question")
        or state.get("effective_query")
        or state.get("question")
        or ""
    )
    patch = run_case_transaction_agent(
        db,
        case_id=str(state.get("case_id") or ""),
        question=question,
        attached_file_ids=state.get("attached_file_ids") or state.get("scoped_file_ids"),
        statement_scope_file_ids=state.get("statement_scope_file_ids"),
        sql_plan_hints=exec_contract.get("sql_plan_hints") if isinstance(exec_contract.get("sql_plan_hints"), dict) else None,
        prior_turn_state=exec_contract.get("prior_turn_state") if isinstance(exec_contract.get("prior_turn_state"), dict) else None,
    )
    return patch or {}


def route_after_case_transaction_agent(state: Dict[str, Any]) -> str:
    from langgraph.graph import END

    from app.services.chat.tier_graph_nodes import route_after_execution_tier

    if state.get("transaction_agent_resolved"):
        return END
    if state.get("sql_attempted_empty"):
        meta = state.get("statement_sql_meta") if isinstance(state.get("statement_sql_meta"), dict) else {}
        scope = list(state.get("statement_scope_file_ids") or [])
        if scope or meta.get("file_id"):
            return "extract_retrieval_task"
    return route_after_execution_tier(state)
