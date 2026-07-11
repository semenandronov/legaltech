"""
LangGraph nodes for adaptive execution tiers (case assistant).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.messages import AIMessage

from app.config import config
from app.services.chat.execution_tier import (
    escalate_tier,
    tier_skips_retrieval,
)

logger = logging.getLogger(__name__)

_CLARIFY_TEMPLATES = {
    "empty_question": "Задайте вопрос по материалам дела.",
    "clarification_markers": "Уточните формулировку или укажите документ / период.",
    "default": (
        "Недостаточно контекста для поиска по делу. "
        "Уточните, какой документ, пункт или сторону имеете в виду."
    ),
}


def sync_execution_tier_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Copy execution_tier from budget_profile; init retrieval_round; case legal intent."""
    bp = dict(state.get("budget_profile") or {})
    tier = str(bp.get("execution_tier") or "standard")
    out: Dict[str, Any] = {
        "execution_tier": tier,
        "retrieval_round": int(state.get("retrieval_round") or 0),
    }
    if state.get("clarification_needed") and tier not in ("clarify", "no_retrieval"):
        out["execution_tier"] = "clarify"
        tier = "clarify"

    from app.services.chat.legal_intent import (
        apply_norm_only_case_budget,
        case_norm_only_enabled,
        classify_case_legal_intent,
    )

    legal_research = bool(
        state.get("legal_research")
        or bp.get("legal_research")
        or state.get("mode") == "garant"
    )
    intent, intent_reason = classify_case_legal_intent(
        str(state.get("question") or ""),
        legal_research=legal_research,
        mode=str(state.get("mode") or ""),
        enable_garant=bool(state.get("enable_garant", True)),
        task_type=str(state.get("task_type") or ""),
        attached_file_ids=state.get("attached_file_ids"),
    )
    out["legal_intent"] = intent
    out["legal_intent_reason"] = intent_reason

    if intent == "norm_only" and case_norm_only_enabled():
        bp = apply_norm_only_case_budget(bp)
        out["budget_profile"] = bp

    logger.info(
        "[SyncExecutionTier] tier=%s legal_intent=%s recall_k=%s rerank=%s rounds=%s",
        tier,
        intent,
        bp.get("recall_k"),
        bp.get("rerank_enabled"),
        bp.get("max_retrieval_rounds"),
    )
    return out


def route_after_execution_tier(state: Dict[str, Any]) -> str:
    from app.services.chat.session_context_retrieval import is_memory_only_turn

    meta = state.get("session_context_meta")
    memory_only = is_memory_only_turn(meta if isinstance(meta, dict) else None)

    tier = str(state.get("execution_tier") or "standard")
    if memory_only:
        target = "generate_response"
        reason = "memory_only"
    elif tier == "clarify":
        target = "clarify_response"
        reason = "clarify_tier"
    elif tier == "no_retrieval":
        target = "generate_response"
        reason = "no_retrieval_tier"
    else:
        target = "extract_retrieval_task"
        reason = "retrieval_required"

    try:
        from app.services.observability.assistant_pipeline_langfuse_tracing import (
            record_execution_branch,
            turn_context_trace_fields,
        )

        tc = {}
        if isinstance(meta, dict):
            tc_source = meta.get("turn_context")
            if not isinstance(tc_source, dict):
                tc_source = meta
            tc = turn_context_trace_fields(tc_source if isinstance(tc_source, dict) else None)
        record_execution_branch(
            "case",
            branch=f"graph_route_{target}",
            reason=reason,
            metadata={
                "execution_tier": tier,
                "memory_only": memory_only,
                **tc,
            },
        )
    except Exception:
        logger.debug("tier route trace failed", exc_info=True)

    return target


def clarify_response_node(state: Dict[str, Any]) -> Dict[str, Any]:
    bp = state.get("budget_profile") or {}
    reason = str(bp.get("tier_reason") or state.get("route_reason") or "")
    text = _CLARIFY_TEMPLATES.get(reason) or _CLARIFY_TEMPLATES["default"]
    return {
        "response": text,
        "messages": [AIMessage(content=text)],
        "rag_context": "",
        "citations": [],
    }


def _heuristic_grade(
    *,
    question: str,
    docs: list,
    recall_meta: Optional[Dict[str, Any]],
) -> Literal["sufficient", "weak"]:
    if not docs:
        return "weak"
    if len(docs) < 2:
        return "weak"
    scores = []
    for d in docs:
        md = getattr(d, "metadata", None) or (d if isinstance(d, dict) else {})
        if isinstance(md, dict):
            for key in ("rerank_score", "score", "relevance_score"):
                v = md.get(key)
                if isinstance(v, (int, float)):
                    scores.append(float(v))
                    break
    if scores and max(scores) < 0.15:
        return "weak"
    if isinstance(recall_meta, dict) and int(recall_meta.get("recall_docs") or len(docs)) < 2:
        return "weak"
    from app.services.chat.retrieval_escalation import question_anchors_covered

    if not question_anchors_covered(question, docs):
        return "weak"
    return "sufficient"


def grade_retrieval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Hybrid RAG: assess whether recalled chunks are sufficient."""
    from app.services.chat.case_context_pipeline import documents_from_state_serializable
    from app.services.chat.legal_intent import (
        court_practice_graded_sufficient,
        legal_corpus_graded_sufficient,
    )

    tier = str(state.get("execution_tier") or "standard")
    if tier_skips_retrieval(tier):
        return {"grade_retrieval_ok": True}

    if court_practice_graded_sufficient(state):
        logger.info(
            "[GradeRetrieval] court practice sufficient, skip case rewrite loop",
        )
        return {"grade_retrieval_ok": True}

    if legal_corpus_graded_sufficient(state):
        logger.info(
            "[GradeRetrieval] legal corpus sufficient (intent=%s), skip case rewrite loop",
            state.get("legal_intent"),
        )
        return {"grade_retrieval_ok": True}

    docs = documents_from_state_serializable(state.get("rag_documents"))
    meta = state.get("context_pipeline_meta") if isinstance(state.get("context_pipeline_meta"), dict) else {}
    verdict = _heuristic_grade(
        question=str(state.get("question") or ""),
        docs=docs,
        recall_meta=meta,
    )

    if verdict == "sufficient":
        return {"grade_retrieval_ok": True}

    bp = dict(state.get("budget_profile") or {})
    max_rounds = int(bp.get("max_retrieval_rounds") or 2)
    current_round = int(state.get("retrieval_round") or 0)
    escalation_enabled = bool(
        getattr(config, "CASE_ASSISTANT_RETRIEVAL_ESCALATION_ENABLED", True)
    )
    latency = bp.get("latency_path") if isinstance(bp.get("latency_path"), dict) else {}
    is_fast = (
        str(latency.get("kind") or "") == "fast"
        or bp.get("skip_llm_document_scope") is True
    )

    # Rounds left for another pass? (round is 0-indexed; max_rounds=2 → escalate at round 0)
    can_escalate = escalation_enabled and current_round < max(1, max_rounds) - 1

    if can_escalate:
        logger.info(
            "[GradeRetrieval] weak → escalate round=%s/%s fast=%s docs=%s",
            current_round,
            max_rounds,
            is_fast,
            len(docs),
        )
        return {"grade_retrieval_ok": False}

    # Exhausted deterministic escalate: optional instant→standard for non-FAST only.
    if (not is_fast) and tier == "instant":
        new_tier = escalate_tier("instant")
        bp = _rebuild_budget_for_tier(bp, new_tier, escalated_from=tier)
        return {
            "grade_retrieval_ok": False,
            "execution_tier": new_tier,
            "budget_profile": bp,
            "escalated_from": tier,
            "retrieval_round": current_round + 1,
        }

    logger.info(
        "[GradeRetrieval] weak accepted (no rounds left) round=%s max=%s fast=%s",
        current_round,
        max_rounds,
        is_fast,
    )
    return {"grade_retrieval_ok": True}


def route_after_grade_retrieval(state: Dict[str, Any]) -> str:
    if state.get("grade_retrieval_ok"):
        return "rag_quality_gate"
    if state.get("escalated_from"):
        return "extract_retrieval_task"
    return "escalate_retrieval"


def _rebuild_budget_for_tier(
    bp: Dict[str, Any],
    tier: str,
    *,
    escalated_from: Optional[str] = None,
) -> Dict[str, Any]:
    from app.services.chat.execution_tier import attach_pipeline_budget_for_tier

    base = {k: v for k, v in bp.items() if k not in ("execution_tier", "recall_k", "final_k", "rerank_enabled", "max_retrieval_rounds")}
    out = attach_pipeline_budget_for_tier(base, tier)  # type: ignore[arg-type]
    if escalated_from:
        out["escalated_from"] = escalated_from
    return out


def escalate_retrieval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic second-pass retrieval planner (broaden / deepen).

    Skips LLM rewrite; locks scope so extract_retrieval_task is not required.
    Graph routes this node directly to parallel_retrieval.
    """
    from app.services.chat.case_context_pipeline import documents_from_state_serializable
    from app.services.chat.retrieval_escalation import (
        build_escalated_retrieval_task,
        bump_recall_k,
        plan_retrieval_escalation,
        serialize_docs_for_state,
    )
    from app.services.chat.session_context_retrieval import question_for_retrieval

    question = question_for_retrieval(state)
    docs = documents_from_state_serializable(state.get("rag_documents"))
    bp = dict(state.get("budget_profile") or {})
    max_rounds = int(bp.get("max_retrieval_rounds") or 2)
    current_round = int(state.get("retrieval_round") or 0)
    prior_task = state.get("retrieval_task") if isinstance(state.get("retrieval_task"), dict) else {}

    plan = plan_retrieval_escalation(
        question=question,
        retrieval_task=prior_task,
        docs=docs,
        retrieval_round=current_round,
        max_rounds=max_rounds,
    )
    if plan.action == "accept":
        return {"grade_retrieval_ok": True}

    new_task = build_escalated_retrieval_task(
        plan=plan,
        question=question,
        prior_task=prior_task,
    )
    bp = bump_recall_k(bp, plan.recall_k_bump)
    out: Dict[str, Any] = {
        "retrieval_task": new_task,
        "scoped_file_ids": list(new_task.get("file_ids") or []) or None,
        "scoped_doc_type": None,
        "retrieval_round": current_round + 1,
        "budget_profile": bp,
        "retrieval_escalation": plan.to_dict(),
        "rag_context": "",
        "citations": [],
        "grade_retrieval_ok": None,
    }
    if plan.merge_prior_docs and docs:
        out["escalation_seed_documents"] = serialize_docs_for_state(docs)[:100]
        out["rag_documents"] = []
    else:
        out["escalation_seed_documents"] = []
        out["rag_documents"] = []

    logger.info(
        "[EscalateRetrieval] action=%s reason=%s files=%s recall_k=%s merge=%s",
        plan.action,
        plan.reason,
        len(new_task.get("file_ids") or []),
        bp.get("recall_k"),
        plan.merge_prior_docs,
    )
    return out


def rewrite_search_query_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy LLM rewrite path — prefer escalate_retrieval_node for production FAST/HEAVY."""
    # Keep for backwards-compatible graphs/tests; delegate to deterministic escalate.
    return escalate_retrieval_node(state)


def parallel_retrieval_should_run(state: Dict[str, Any]) -> bool:
    tier = str(state.get("execution_tier") or "")
    if tier_skips_retrieval(tier):
        return False
    return True
