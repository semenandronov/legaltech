"""
Retrieval query contract for in-dialog session context.

Single source of truth: SessionContextPackage.retrieval_query is computed once per turn
and passed through graph state (session_context_meta). Retrieval nodes read it via
question_for_retrieval(state) — never re-run session assembly inside the graph.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from langchain_core.messages import BaseMessage

from app.services.chat.session_context_types import (
    SessionContextPackage,
    SessionResolveResult,
    TurnRelation,
)

MEMORY_ONLY_SYSTEM_PROMPT = (
    "Ты продолжаешь тот же чат с пользователем (юридический ассистент).\n"
    "Ответь на текущий вопрос, опираясь ТОЛЬКО на историю диалога и контекст сессии ниже.\n"
    "Не выполняй новый поиск по документам, нормам и судебной практике и не добавляй факты, "
    "которых не было в прошлых репликах этого чата.\n"
    "Если в переписке нет данных для ответа — честно скажи об этом.\n"
    "Пиши по-русски, профессионально и по делу."
)


def build_memory_only_user_prompt(
    *,
    question: str,
    session_context_prompt: Optional[str] = None,
    conversation_summary: Optional[str] = None,
    dialog_history: Optional[str] = None,
) -> str:
    """User prompt for memory-only turns (global + in-case assistant)."""
    session_ctx = (session_context_prompt or "").strip()
    session_section = f"{session_ctx}\n\n" if session_ctx else ""
    summary = (conversation_summary or "").strip() or "[нет]"
    history = (dialog_history or "").strip() or "[нет]"
    q = (question or "").strip()
    return (
        f"{session_section}"
        f"Сводка прошлых сообщений:\n{summary}\n\n"
        f"История диалога:\n{history}\n\n"
        f"Текущий вопрос:\n{q}\n"
    )


def format_dialog_history_for_memory(
    messages: Sequence[BaseMessage],
    *,
    message_summary: str = "",
    max_turns: int = 16,
    max_chars: int = 6400,
) -> str:
    from app.services.chat.langgraph_dialog_memory import format_messages_for_prompt

    return format_messages_for_prompt(
        messages,
        message_summary=message_summary,
        max_turns=max_turns,
        max_chars=max_chars,
    )


def build_retrieval_query(
    question: str,
    *,
    thread_state: Optional[Dict[str, Any]] = None,
    conversation_summary: str = "",
    resolver: Optional[SessionResolveResult] = None,
) -> str:
    """
    Compact query for case RAG / legal corpus / court practice search.

    Rules (production contract):
    - new_topic: use only the current question (no carry-over from prior thread).
    - follow_up / clarify_prior: prepend structured session signals (topic, focus, summary).
    """
    q = (question or "").strip()
    if not q:
        return q

    rel = (resolver.turn_relation if resolver else TurnRelation.FOLLOW_UP)
    if rel is TurnRelation.NEW_TOPIC:
        return q

    segments: list[str] = []
    ts = thread_state or {}
    topic = str(ts.get("topic") or ts.get("last_user_intent") or "").strip()
    if topic:
        segments.append(topic[:400])

    focus = (resolver.focus if resolver else "").strip()
    if focus:
        segments.append(focus[:400])
    elif (conversation_summary or "").strip():
        segments.append(conversation_summary.strip()[:600])

    segments.append(q)
    return "\n".join(s for s in segments if s)


def attach_retrieval_query(package: SessionContextPackage, question: str) -> SessionContextPackage:
    """Fill retrieval_query on an assembled package (immutable-friendly copy)."""
    rq = build_retrieval_query(
        question,
        thread_state=package.thread_state,
        conversation_summary=package.conversation_summary,
        resolver=package.resolver,
    )
    package.retrieval_query = rq
    return package


def session_context_meta_from_package(
    package: SessionContextPackage,
    *,
    turn_context: Optional[dict] = None,
) -> Dict[str, Any]:
    """Serializable slice for LangGraph state — no ORM / no re-fetch."""
    meta: Dict[str, Any] = {
        "retrieval_query": (package.retrieval_query or "").strip(),
        "turn_relation": package.resolver.turn_relation.value,
        "needs_document_retrieval": bool(package.resolver.needs_document_retrieval),
        "focus": package.resolver.focus,
        "confidence": package.resolver.confidence,
        "session_key": package.session_key,
        "should_replay_prior_answer": package.resolver.should_replay_prior_answer,
        "replay_short_circuit": package.evidence_replay is not None,
        "prior_answer_available": bool(package.prior_answer_available),
        "prior_answer_message_id": (package.prior_answer_message_id or "").strip(),
        "prior_answer_excerpt": (package.prior_answer_excerpt or "").strip(),
    }
    if isinstance(turn_context, dict):
        meta["turn_context"] = turn_context
        meta["referential_kind"] = str(turn_context.get("referential_kind") or "none")
        inherited = turn_context.get("inherited_file_ids") or []
        if inherited:
            meta["inherited_file_ids"] = list(inherited)
    return meta


def align_budget_profile_with_session(
    budget_profile: Dict[str, Any],
    package: SessionContextPackage,
) -> Dict[str, Any]:
    """
    Keep execution tier consistent with session resolver (single contract per turn).

    Prevents no_retrieval tier without session prompt in the graph, and avoids
    skipping retrieval when the session resolver still requires document context.
    """
    from app.services.chat.execution_tier import attach_pipeline_budget_for_tier

    out = dict(budget_profile or {})
    resolver = package.resolver
    tier = str(out.get("execution_tier") or "standard").strip().lower()

    if package.prior_answer_available and resolver.prefers_memory_only:
        if tier != "no_retrieval":
            out = attach_pipeline_budget_for_tier(
                out,
                "no_retrieval",
                tier_reason="session_memory_only",
                response_shape=str(out.get("response_shape") or "brief"),
                response_shape_reason="session_resolver",
            )
    elif resolver.needs_document_retrieval and tier in {"no_retrieval", "clarify"}:
        out = attach_pipeline_budget_for_tier(
            out,
            "instant",
            tier_reason="session_retrieval_required",
            response_shape=str(out.get("response_shape") or "fact"),
            response_shape_reason="session_resolver",
        )

    rq = (package.retrieval_query or "").strip()
    if rq:
        out["session_retrieval_query"] = rq
    return out


def is_memory_only_turn(meta: Optional[Mapping[str, Any]]) -> bool:
    """
    Answer from in-chat memory without fresh document/corpus retrieval.

    memory_synthesis (turn context) or clarify_prior without retrieval may bypass RAG.
    """
    if not isinstance(meta, dict):
        return False
    if meta.get("replay_short_circuit"):
        return True
    if str(meta.get("referential_kind") or "") == "memory_synthesis":
        return bool(meta.get("prior_answer_available"))
    if not bool(meta.get("prior_answer_available")):
        return False
    if str(meta.get("turn_relation") or "") != TurnRelation.CLARIFY_PRIOR.value:
        return False
    if "needs_document_retrieval" in meta:
        return not bool(meta.get("needs_document_retrieval"))
    return True


def is_thread_clarify_turn(meta: Optional[Mapping[str, Any]]) -> bool:
    """Backward-compatible alias for is_memory_only_turn."""
    return is_memory_only_turn(meta)


def question_for_retrieval(state: Mapping[str, Any]) -> str:
    """
    Query for all retrieval nodes in case graph.

    Prefers session_context_meta.retrieval_query assembled at turn start;
    falls back to raw question.
    """
    meta = state.get("session_context_meta")
    if isinstance(meta, dict):
        rq = str(meta.get("retrieval_query") or "").strip()
        if rq:
            return rq
    return str(state.get("question") or "").strip()


def should_reuse_retrieval_task(
    state: Mapping[str, Any],
    existing_task: Mapping[str, Any],
) -> bool:
    """Re-use scoped task only when search query still matches session retrieval query."""
    prev_sq = str(existing_task.get("search_query") or "").strip()
    if not prev_sq:
        return False
    current = question_for_retrieval(state)
    return prev_sq == current
