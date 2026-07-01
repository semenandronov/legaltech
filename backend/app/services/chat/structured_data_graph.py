"""ChatGraph integration for structured-data (SQL vs RAG vs hybrid) LLM router."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.chat.structured_data_scope_gate import (
    resolve_turn_file_scope,
    route_structured_data_for_turn,
)
from app.services.chat.tier_graph_nodes import route_after_execution_tier
from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span

logger = logging.getLogger(__name__)


def _router_result_to_state(result) -> Dict[str, Any]:
    return {
        "structured_data_plane": result.data_plane,
        "statement_scope_file_ids": list(result.statement_file_ids),
        "hybrid_rag_file_ids": list(result.rag_file_ids),
        "structured_data_router_meta": {
            "resolver": result.resolver,
            "confidence": result.confidence,
            "reason": result.reason,
            "statement_file_ids": list(result.statement_file_ids),
            "rag_file_ids": list(result.rag_file_ids),
            "information_need": result.information_need,
        },
    }


def structured_data_router_node(
    state: Dict[str, Any],
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """Classify turn: SQL / hybrid / document RAG. Skips LLM if HTTP prep already routed."""
    existing_plane = str(state.get("structured_data_plane") or "").strip().lower()
    meta = state.get("structured_data_router_meta")
    if existing_plane and isinstance(meta, dict) and meta.get("resolver"):
        logger.debug(
            "[StructuredDataRouter] Reusing HTTP prep plane=%s resolver=%s",
            existing_plane,
            meta.get("resolver"),
        )
        return {}

    if db is None:
        return {"structured_data_plane": "rag"}

    bp = state.get("budget_profile") if isinstance(state.get("budget_profile"), dict) else {}
    exec_contract = (
        bp.get("execution_contract") if isinstance(bp.get("execution_contract"), dict) else {}
    )

    turn_context = bp.get("turn_context") if isinstance(bp.get("turn_context"), dict) else {}
    turn_scope = resolve_turn_file_scope(
        attached_file_ids=state.get("attached_file_ids"),
        turn_context=turn_context,
        prior_evidence=None,
        information_need=str(
            exec_contract.get("information_need")
            or bp.get("information_need")
            or "unknown"
        ),
    )

    with assistant_step_span(
        "case",
        "graph.router.data_plane",
        metadata={"router_role": "data_plane"},
        input_payload={"question": str(state.get("question") or "")[:800]},
    ) as span_out:
        result = route_structured_data_for_turn(
            db,
            case_id=str(state.get("case_id") or ""),
            question=str(
                exec_contract.get("effective_query")
                or bp.get("effective_query")
                or bp.get("resolved_question")
                or state.get("effective_query")
                or state.get("question")
                or ""
            ),
            turn_scope=turn_scope,
            attached_file_ids=state.get("attached_file_ids"),
            dialog_history=str(bp.get("dialog_history") or "") or None,
            resolver_hint="graph",
            information_need=str(
                exec_contract.get("information_need")
                or bp.get("information_need")
                or "unknown"
            ),
        )
        span_out["data_plane"] = result.data_plane
        span_out["confidence"] = result.confidence
        span_out["resolver"] = result.resolver
        span_out["turn_scope_source"] = turn_scope.source
    return _router_result_to_state(result)


def route_after_structured_data_router(state: Dict[str, Any]) -> str:
    """Route to SQL, hybrid, or normal fast RAG tier path."""
    plane = str(state.get("structured_data_plane") or "rag").strip().lower()
    if plane == "sql":
        return "case_transaction_agent"
    if plane == "hybrid":
        return "hybrid_structured_agent"
    return "extract_retrieval_task"


def route_after_sync_tier(state: Dict[str, Any]) -> str:
    """
    After tier sync: clarify / no-retrieval shortcuts, else structured-data router
  (or legacy direct RAG).
    """
    from app.config import config

    target = route_after_execution_tier(state)
    if target != "extract_retrieval_task":
        return target
    if bool(getattr(config, "CASE_ASSISTANT_LEGACY_PIPELINE_ENABLED", False)):
        return "extract_retrieval_task"
    return "structured_data_router"
