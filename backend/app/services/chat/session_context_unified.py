"""
Unified session context meta from TurnMemoryContract.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.services.chat.session_context_retrieval import (
    align_budget_profile_with_session,
    session_context_meta_from_package,
)
from app.services.chat.session_context_service import build_session_context_for_turn
from app.services.chat.session_context_types import TurnRelation
from app.services.chat.turn_memory_contract import (
    TurnMemoryContract,
    memory_contract_forces_scoped_rag,
    memory_contract_skips_structured_router,
)


def _prior_answer_fields(contract: TurnMemoryContract) -> tuple[bool, str, str]:
    prior = contract.prior_evidence
    if prior is None:
        return False, "", ""
    excerpt = (prior.assistant_excerpt or "").strip()
    if not excerpt:
        return False, "", ""
    return True, prior.message_id, excerpt[:1800]


def build_session_meta_from_memory_contract(
    contract: TurnMemoryContract,
    *,
    case_id: str,
    session_id: str,
    question: str,
    routing_question: str,
) -> Dict[str, Any]:
    """Session meta slice when contract already resolved routing (no duplicate LLM)."""
    turn_relation, needs_docs = contract.session_resolver_hints()
    prior_available, prior_mid, prior_excerpt = _prior_answer_fields(contract)
    mode = contract.execution_mode
    meta: Dict[str, Any] = {
        "execution_mode": mode,
        "memory_contract": contract.to_dict(),
        "retrieval_query": (routing_question or question).strip(),
        "turn_relation": turn_relation.value,
        "needs_document_retrieval": needs_docs,
        "focus": contract.original_question[:500],
        "confidence": contract.confidence,
        "session_key": f"case:{case_id}:{session_id}",
        "should_replay_prior_answer": mode == "chat_replay",
        "replay_short_circuit": False,
        "prior_answer_available": prior_available,
        "prior_answer_message_id": prior_mid,
        "prior_answer_excerpt": prior_excerpt,
        "turn_context": contract.turn_context_dict,
        "referential_kind": contract.turn_context.referential_kind,
        "execution_contract": contract.execution_contract_dict,
    }
    inherited = contract.turn_context.inherited_file_ids
    if inherited:
        meta["inherited_file_ids"] = list(inherited)
    return meta


def build_sql_turn_session_meta(
    *,
    case_id: str,
    session_id: str,
    question: str,
    routing_question: str,
    turn_context: Optional[Dict[str, Any]],
    execution_contract: Optional[Dict[str, Any]],
    memory_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    has_prior = bool(
        isinstance(execution_contract, dict) and execution_contract.get("prior_turn_state")
    )
    mode = "structured_sql"
    if isinstance(memory_contract, dict):
        mode = str(memory_contract.get("execution_mode") or mode)
    return {
        "execution_mode": mode,
        "memory_contract": memory_contract,
        "retrieval_query": (routing_question or question).strip(),
        "turn_relation": TurnRelation.FOLLOW_UP.value if has_prior else TurnRelation.NEW_TOPIC.value,
        "needs_document_retrieval": False,
        "focus": (question or "")[:500],
        "confidence": 0.9,
        "session_key": f"case:{case_id}:{session_id}",
        "should_replay_prior_answer": False,
        "replay_short_circuit": False,
        "prior_answer_available": has_prior,
        "prior_answer_message_id": "",
        "prior_answer_excerpt": "",
        "turn_context": turn_context,
        "referential_kind": str((turn_context or {}).get("referential_kind") or "none"),
        "execution_contract": execution_contract,
    }


def build_case_session_context(
    db,
    *,
    case_id: str,
    session_id: str,
    question: str,
    routing_question: str,
    structured_data_plane: Optional[str],
    turn_context: Optional[Dict[str, Any]],
    execution_contract: Optional[Dict[str, Any]],
    memory_contract: Optional[TurnMemoryContract] = None,
    task_type: str,
    corpus_size: int,
    draft_mode: bool,
    skip_semantic_search: bool,
    budget_profile: Optional[Dict[str, Any]] = None,
) -> tuple[Optional[str], Dict[str, Any]]:
    """
    Returns (prompt_block, session_context_meta).

    When ``memory_contract`` is provided, session routing follows the contract
    instead of a second LLM resolver.
    """
    contract = memory_contract
    contract_dict = contract.to_dict() if contract is not None else None

    if contract is not None and memory_contract_skips_structured_router(contract):
        package = build_session_context_for_turn(
            db,
            scope="case",
            question=question,
            session_id=session_id,
            case_id=case_id,
            task_type=task_type,
            corpus_size=corpus_size,
            draft_mode=draft_mode,
            turn_context=turn_context,
            skip_semantic_search=True,
        )
        meta = build_session_meta_from_memory_contract(
            contract,
            case_id=case_id,
            session_id=session_id,
            question=question,
            routing_question=routing_question,
        )
        if isinstance(budget_profile, dict):
            align_budget_profile_with_session(budget_profile, package)
            from app.services.chat.execution_tier import attach_pipeline_budget_for_tier

            budget_profile.update(
                attach_pipeline_budget_for_tier(
                    budget_profile,
                    "no_retrieval",
                    tier_reason="memory_contract_chat_replay",
                    response_shape=str(budget_profile.get("response_shape") or "brief"),
                    response_shape_reason="turn_memory_contract",
                )
            )
        prompt = (package.prompt_block or "").strip() or None
        return prompt, meta

    plane = (structured_data_plane or "").strip().lower()
    if plane == "sql":
        return None, build_sql_turn_session_meta(
            case_id=case_id,
            session_id=session_id,
            question=question,
            routing_question=routing_question,
            turn_context=turn_context,
            execution_contract=execution_contract,
            memory_contract=contract_dict,
        )

    skip_search = skip_semantic_search or (
        contract is not None and memory_contract_forces_scoped_rag(contract)
    )
    package = build_session_context_for_turn(
        db,
        scope="case",
        question=question,
        session_id=session_id,
        case_id=case_id,
        task_type=task_type,
        corpus_size=corpus_size,
        draft_mode=draft_mode,
        turn_context=turn_context,
        skip_semantic_search=skip_search,
    )
    meta = session_context_meta_from_package(package, turn_context=turn_context)
    if contract is not None:
        meta = build_session_meta_from_memory_contract(
            contract,
            case_id=case_id,
            session_id=session_id,
            question=question,
            routing_question=routing_question,
        )
        meta["replay_short_circuit"] = package.evidence_replay is not None
    elif isinstance(execution_contract, dict):
        meta["execution_contract"] = execution_contract
    if contract_dict is not None:
        meta["memory_contract"] = contract_dict
    if routing_question.strip():
        meta["retrieval_query"] = routing_question.strip()
    if isinstance(budget_profile, dict):
        align_budget_profile_with_session(budget_profile, package)
    return (package.prompt_block or "").strip() or None, meta
