"""ChatGraph integration for hybrid SQL + RAG path."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langgraph.graph import END
from sqlalchemy.orm import Session

from app.services.chat.hybrid_structured_agent import run_hybrid_structured_agent

logger = logging.getLogger(__name__)


def hybrid_structured_agent_node(
    state: Dict[str, Any],
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    if db is None:
        return {}
    patch = run_hybrid_structured_agent(
        db,
        case_id=str(state.get("case_id") or ""),
        question=str(state.get("question") or ""),
        statement_scope_file_ids=state.get("statement_scope_file_ids") or [],
        rag_file_ids=state.get("hybrid_rag_file_ids") or [],
        attached_file_ids=state.get("attached_file_ids"),
        budget_profile=state.get("budget_profile"),
    )
    return patch or {}


def route_after_hybrid_structured_agent(state: Dict[str, Any]) -> str:
    if state.get("hybrid_agent_resolved") or state.get("transaction_agent_resolved"):
        return END
    from app.services.chat.tier_graph_nodes import route_after_execution_tier

    return route_after_execution_tier(state)
