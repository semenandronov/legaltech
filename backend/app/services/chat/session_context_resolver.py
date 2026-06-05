"""
Session turn router: dialog relation + memory vs document retrieval (one LLM call).
"""
from __future__ import annotations

import logging
from typing import List, Literal, Optional, Sequence

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app.config import config
from app.services.chat.session_context_types import (
    RelevantTurn,
    SessionMessageTurn,
    SessionResolveResult,
    TurnRelation,
)
from app.services.chat.session_replay_policy import (
    find_last_assistant_turn,
    infer_clarify_from_session_signals,
)
from app.services.chat.session_transcript import turns_to_resolver_transcript
from app.services.llm_factory import create_legal_llm
from app.services.observability.langfuse_service import get_langchain_callbacks

logger = logging.getLogger(__name__)


class SessionTurnRoutingDecision(BaseModel):
    """Structured router output — single decision point per user turn."""

    turn_relation: Literal["new_topic", "follow_up", "clarify_prior"] = "follow_up"
    needs_document_retrieval: bool = Field(
        description=(
            "True if the answer requires searching case files, legal corpus, or court practice. "
            "False if the existing chat transcript already contains enough facts to answer."
        )
    )
    focus: str = ""
    anchor_message_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""


def resolve_turn_semantic(
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    search_hits: Sequence[RelevantTurn],
    trace_scope: Literal["case", "global"] = "case",
    primary_intent: Optional[str] = None,
    intent_confidence: float = 0.0,
    turn_context: Optional[dict] = None,
) -> SessionResolveResult:
    """
    Route the turn: how it relates to the dialog and whether external retrieval is needed.
    """
    if not getattr(config, "SESSION_CONTEXT_RESOLVER_ENABLED", True):
        return fallback_resolve(question, turns, search_hits)

    q = (question or "").strip()
    if not q:
        return SessionResolveResult(
            turn_relation=TurnRelation.NEW_TOPIC,
            needs_document_retrieval=False,
            confidence=0.0,
        )

    authority = resolve_turn_from_intent_authority(
        primary_intent=primary_intent,
        intent_confidence=intent_confidence,
        question=q,
        turns=turns,
        search_hits=search_hits,
        turn_context=turn_context,
    )
    if authority is not None:
        return authority

    transcript = turns_to_resolver_transcript(list(turns), max_turns=12)
    hits_block = "\n".join(
        f"- [{h.message_id}] ({h.role}, score={h.score:.3f}): {(h.content or '')[:400]}"
        for h in list(search_hits)[:6]
    ) or "[нет]"

    llm = create_legal_llm(use_rate_limiting=False, temperature=0.0, max_tokens=600)
    callbacks = get_langchain_callbacks(tags=["assistant", "session_context", "router"])
    prompt = (
        "Ты маршрутизатор юридического ассистента. По транскрипту чата и новому вопросу реши:\n"
        "1) как вопрос связан с диалогом;\n"
        "2) нужен ли НОВЫЙ поиск по документам/нормам/судпрактике или достаточно памяти чата.\n\n"
        "turn_relation:\n"
        "- new_topic: новая тема, мало связи с прошлым.\n"
        "- follow_up: продолжение/углубление той же темы.\n"
        "- clarify_prior: уточнение/пересказ/сужение прошлого ответа ассистента.\n\n"
        "needs_document_retrieval:\n"
        "- false: ответ уже есть в переписке (пересказ, уточнение формулировки, "
        "«что ты имел в виду», «кратко повтори», «а по пункту 2 из твоего ответа»).\n"
        "- true: нужны новые факты из внешних источников (найти/показать в документах, "
        "другое дело, новая норма, другой период, сравнение с материалами дела, "
        "которых ещё не было в чате).\n\n"
        "Если пользователь повторяет тот же вопрос, что уже задавал в транскрипте — "
        "needs_document_retrieval=true, turn_relation=follow_up (нужен новый ответ, не replay).\n"
        "clarify_prior допустим только когда needs_document_retrieval=false "
        "(ответ уже есть в переписке и нужен пересказ/уточнение формулировки).\n"
        "Если сомневаешься и в чате нет нужных фактов — needs_document_retrieval=true.\n"
        "anchor_message_ids: 0–3 id из транскрипта (в квадратных скобках), наиболее релевантных.\n\n"
        f"Транскрипт:\n{transcript or '[пусто]'}\n\n"
        f"Релевантные фрагменты (поиск по сессии):\n{hits_block}\n\n"
        f"Новый вопрос:\n{q}\n"
    )
    try:
        from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span

        with assistant_step_span(
            trace_scope,
            "session_context.resolver_llm",
            input_payload={"question_chars": len(q), "turns_count": len(turns)},
        ) as llm_out:
            if hasattr(llm, "with_structured_output"):
                judge = llm.with_structured_output(SessionTurnRoutingDecision)
                decision: SessionTurnRoutingDecision = judge.invoke(
                    [HumanMessage(content=prompt)],
                    config={"callbacks": callbacks} if callbacks else None,
                )
            else:
                raise RuntimeError("structured output unavailable")
            llm_out["turn_relation"] = decision.turn_relation
            llm_out["needs_document_retrieval"] = decision.needs_document_retrieval
            return _result_from_decision(decision)
    except Exception as exc:
        logger.debug("session router structured LLM failed: %s", exc)

    return fallback_resolve(q, turns, search_hits)


def resolve_turn_from_intent_authority(
    *,
    primary_intent: Optional[str],
    intent_confidence: float,
    question: str,
    turns: Sequence[SessionMessageTurn],
    search_hits: Sequence[RelevantTurn],
    turn_context: Optional[dict] = None,
) -> Optional[SessionResolveResult]:
    """
    HTTP intent layer is authoritative for retrieval vs memory when confidence is high.

    Session resolver handles reference anchors only — no LLM re-classification.
    Turn context contract overrides intent authority for referential follow-ups.
    """
    if isinstance(turn_context, dict):
        kind = str(turn_context.get("referential_kind") or "none").strip().lower()
        if kind != "none":
            return None
    if not getattr(config, "SESSION_CONTEXT_INTENT_AUTHORITY_ENABLED", True):
        return None

    intent = (primary_intent or "").strip().lower()
    if not intent:
        return None

    min_conf = float(
        getattr(config, "SESSION_CONTEXT_INTENT_AUTHORITY_MIN_CONF", 0.72) or 0.72
    )
    if float(intent_confidence or 0.0) < min_conf:
        return None

    retrieval_intents = {
        "drill_down",
        "narrow_fact",
        "standard_case_qa",
        "legal_analysis",
        "cross_doc_analysis",
        "case_corpus_overview",
    }
    if intent not in retrieval_intents:
        return None

    anchor_ids: List[str] = []
    for h in list(search_hits)[:2]:
        if h.message_id:
            anchor_ids.append(h.message_id)
    last = find_last_assistant_turn(turns)
    if last and last.message_id and last.message_id not in anchor_ids:
        anchor_ids.append(last.message_id)

    rel = TurnRelation.FOLLOW_UP if turns else TurnRelation.NEW_TOPIC
    return SessionResolveResult(
        turn_relation=rel,
        needs_document_retrieval=True,
        focus=question[:500],
        anchor_message_ids=anchor_ids[:3],
        confidence=max(min_conf, float(intent_confidence or min_conf)),
        rationale=f"intent_authority_{intent}",
    )


def _result_from_decision(decision: SessionTurnRoutingDecision) -> SessionResolveResult:
    rel_raw = str(decision.turn_relation or "follow_up").strip().lower()
    if rel_raw == "new_topic":
        rel = TurnRelation.NEW_TOPIC
    elif rel_raw == "clarify_prior":
        rel = TurnRelation.CLARIFY_PRIOR
    else:
        rel = TurnRelation.FOLLOW_UP

    anchor_ids = [str(x).strip() for x in (decision.anchor_message_ids or []) if str(x).strip()][:3]
    conf = max(0.0, min(1.0, float(decision.confidence or 0.5)))
    needs_docs = bool(decision.needs_document_retrieval)
    if rel is TurnRelation.CLARIFY_PRIOR and needs_docs:
        rel = TurnRelation.FOLLOW_UP

    return SessionResolveResult(
        turn_relation=rel,
        needs_document_retrieval=needs_docs,
        focus=str(decision.focus or "").strip()[:500],
        anchor_message_ids=anchor_ids,
        confidence=conf,
        rationale=str(decision.rationale or "").strip()[:300],
    )


def fallback_resolve(
    question: str,
    turns: Sequence[SessionMessageTurn],
    search_hits: Sequence[RelevantTurn],
) -> SessionResolveResult:
    """Conservative fallback when the router LLM is unavailable."""
    if not turns:
        return SessionResolveResult(
            turn_relation=TurnRelation.NEW_TOPIC,
            needs_document_retrieval=True,
            confidence=0.3,
            rationale="empty_thread",
        )

    anchor_ids: List[str] = []
    if search_hits:
        anchor_ids = [search_hits[0].message_id]
    else:
        last = find_last_assistant_turn(turns)
        if last:
            anchor_ids = [last.message_id]

    last_assistant = find_last_assistant_turn(turns)
    if not last_assistant:
        rel = TurnRelation.NEW_TOPIC if len(turns) <= 1 else TurnRelation.FOLLOW_UP
        needs_docs = True
    elif infer_clarify_from_session_signals(
        question=question, turns=turns, search_hits=search_hits
    ):
        rel = TurnRelation.CLARIFY_PRIOR
        needs_docs = False
    else:
        rel = TurnRelation.FOLLOW_UP
        needs_docs = True

    return SessionResolveResult(
        turn_relation=rel,
        needs_document_retrieval=needs_docs,
        focus=question[:200],
        anchor_message_ids=anchor_ids,
        confidence=0.55 if not needs_docs else 0.45,
        rationale="router_fallback",
    )
