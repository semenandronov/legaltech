"""
LangGraph nodes for adaptive execution tiers (case assistant).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

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
    if current_round >= max_rounds - 1:
        if tier == "instant":
            new_tier = escalate_tier("instant")
            bp = _rebuild_budget_for_tier(bp, new_tier, escalated_from=tier)
            return {
                "grade_retrieval_ok": False,
                "execution_tier": new_tier,
                "budget_profile": bp,
                "escalated_from": tier,
                "retrieval_round": current_round + 1,
            }
        return {"grade_retrieval_ok": True}

    return {"grade_retrieval_ok": False}


def route_after_grade_retrieval(state: Dict[str, Any]) -> str:
    if state.get("grade_retrieval_ok"):
        return "rag_quality_gate"
    if state.get("escalated_from"):
        return "extract_retrieval_task"
    return "rewrite_search_query"


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


def rewrite_search_query_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Rewrite search_query for a second retrieval pass."""
    from app.services.chat.session_context_retrieval import question_for_retrieval

    question = question_for_retrieval(state)
    rt = dict(state.get("retrieval_task") or {})
    prev_q = str(rt.get("search_query") or question)

    new_q = prev_q
    try:
        if bool(getattr(config, "CASE_ASSISTANT_LLM_ROUTER_ENABLED", False)):
            from app.services.llm_factory import create_llm

            model = getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", "") or "yandexgpt-lite/latest"
            llm = create_llm(model=model, temperature=0.0, max_tokens=256)
            resp = llm.invoke(
                [
                    SystemMessage(
                        content=(
                            "Перепиши поисковый запрос для юридического дела. "
                            "Только одна строка запроса, без пояснений."
                        )
                    ),
                    HumanMessage(
                        content=f"Вопрос юриста: {question}\nПредыдущий запрос: {prev_q}"
                    ),
                ]
            )
            text = resp.content if hasattr(resp, "content") else str(resp)
            if isinstance(text, str) and text.strip():
                new_q = text.strip()[:500]
    except Exception as exc:
        logger.warning("[RewriteSearchQuery] LLM rewrite failed: %s", exc)
        new_q = f"{question} {prev_q}".strip()[:500]

    rt["search_query"] = new_q
    rt["rationale"] = (rt.get("rationale") or "") + "+rewrite_pass"
    out: Dict[str, Any] = {
        "retrieval_task": rt,
        "retrieval_round": int(state.get("retrieval_round") or 0) + 1,
        "rag_documents": [],
        "rag_context": "",
        "citations": [],
    }
    logger.info("[RewriteSearchQuery] %s -> %s", prev_q[:80], new_q[:80])
    return out


def parallel_retrieval_should_run(state: Dict[str, Any]) -> bool:
    tier = str(state.get("execution_tier") or "")
    if tier_skips_retrieval(tier):
        return False
    if state.get("mode") == "draft":
        return False
    return True
