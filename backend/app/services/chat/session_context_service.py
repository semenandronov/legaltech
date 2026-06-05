"""
Session Context Service — always-on in-dialog memory (no phrase triggers).

Pipeline per user turn:
1. Load thread state (always inject)
2. Semantic search over session messages
3. LLM resolver (new_topic | follow_up | clarify_prior + anchors)
4. Optional in-thread transcript replay for clarify_prior (no fresh RAG)
5. Format prompt block for LLM / graph
"""
from __future__ import annotations

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.editor_session import is_editor_session_id
from app.services.chat.session_context_keys import case_session_key, global_session_key
from app.services.chat.session_context_resolver import resolve_turn_semantic
from app.services.chat.session_context_types import (
    RelevantTurn,
    Scope,
    SessionContextPackage,
    SessionMessageTurn,
    SessionResolveResult,
    TurnRelation,
)
from app.services.chat.session_evidence_anchor import build_evidence_anchor_reply, find_turn_by_id
from app.services.chat.session_replay_policy import (
    apply_corpus_retrieval_policy,
    apply_session_turn_contract,
    enrich_resolver_with_session_signals,
    find_last_assistant_turn,
    resolve_replay_target,
)
from app.services.chat.session_message_index import (
    index_session_turns,
    search_session_messages,
    session_message_index_enabled,
)
from app.services.chat.session_thread_state import (
    format_thread_state_block,
    load_session_thread,
    update_thread_state_after_turn,
)
from app.services.chat.session_context_retrieval import (
    attach_retrieval_query,
    build_retrieval_query,
    session_context_meta_from_package,
)
from app.services.chat.session_transcript import (
    load_case_session_turns,
    load_global_session_turns,
)

logger = logging.getLogger(__name__)


def session_context_enabled() -> bool:
    return bool(getattr(config, "SESSION_CONTEXT_ENABLED", True))


def _max_relevant_turns() -> int:
    return max(1, int(getattr(config, "SESSION_CONTEXT_MAX_RELEVANT_TURNS", 5) or 5))


def _format_relevant_turns_block(turns: List[RelevantTurn]) -> str:
    if not turns:
        return ""
    lines = ["=== РЕЛЕВАНТНЫЕ РЕПЛИКИ ИЗ ЭТОГО ЧАТА (поиск по смыслу) ==="]
    for t in turns[: _max_relevant_turns()]:
        role = "Пользователь" if (t.role or "").lower() == "user" else "Ассистент"
        lines.append(f"[{t.message_id}] {role}:\n{(t.content or '')[:2500]}")
    return "\n\n".join(lines)


def _merge_relevant_turns(
    search_hits: List[RelevantTurn],
    turns: List[SessionMessageTurn],
    anchor_ids: List[str],
) -> List[RelevantTurn]:
    by_id: dict[str, RelevantTurn] = {}
    for h in search_hits:
        by_id[h.message_id] = h
    for aid in anchor_ids:
        if aid in by_id:
            continue
        row = find_turn_by_id(turns, aid)
        if row:
            by_id[aid] = RelevantTurn(
                message_id=row.message_id,
                role=row.role,
                content=row.content,
                score=1.0,
                source="resolver_anchor",
            )
    ordered = sorted(by_id.values(), key=lambda x: x.score, reverse=True)
    return ordered[: _max_relevant_turns()]


def build_session_context_for_turn(
    db: Session,
    *,
    scope: Scope,
    question: str,
    session_id: str,
    case_id: Optional[str] = None,
    exclude_last_user_duplicate: bool = True,
    task_type: Optional[str] = None,
    corpus_size: int = 0,
    draft_mode: bool = False,
    primary_intent: Optional[str] = None,
    intent_confidence: float = 0.0,
    turn_context: Optional[dict] = None,
) -> SessionContextPackage:
    """
    Assemble always-on session context before routing / LLM.
    """
    from app.services.observability.assistant_pipeline_langfuse_tracing import assistant_step_span

    assistant_scope = "case" if scope == "case" else "global"

    if not session_context_enabled():
        return _empty_package(scope, session_id, case_id)

    with assistant_step_span(
        assistant_scope,
        "session_context",
        input_payload={"session_id": session_id, "question_chars": len(question or "")},
        metadata={"case_id": case_id or ""},
    ) as root_out:
        if scope == "case":
            sk = case_session_key(case_id or "", session_id)
            if not sk or is_editor_session_id(session_id):
                root_out["skipped"] = "editor_or_empty_session"
                return _empty_package(scope, session_id, case_id)
            with assistant_step_span(assistant_scope, "session_context.load_turns") as load_out:
                turns = load_case_session_turns(db, case_id=case_id or "", session_id=session_id)
                load_out["turns_count"] = len(turns)
        else:
            sk = global_session_key(session_id)
            if not sk:
                root_out["skipped"] = "empty_session_key"
                return _empty_package(scope, session_id, case_id)
            with assistant_step_span(assistant_scope, "session_context.load_turns") as load_out:
                turns = load_global_session_turns(db, session_id=session_id)
                load_out["turns_count"] = len(turns)

        q = (question or "").strip()
        if exclude_last_user_duplicate and turns and q:
            last = turns[-1]
            if (last.role or "").lower() == "user" and (last.content or "").strip() == q:
                turns = turns[:-1]

        if scope == "case":
            from app.services.chat.case_metadata_service import is_case_metadata_question

            if is_case_metadata_question(q):
                root_out["skipped"] = "case_card_metadata"
                resolver = SessionResolveResult(
                    turn_relation=TurnRelation.FOLLOW_UP,
                    needs_document_retrieval=False,
                    focus=q[:200],
                    confidence=0.95,
                    rationale="case_card_metadata",
                )
                package = SessionContextPackage(
                    scope=scope,
                    session_key=sk,
                    prompt_block="",
                    thread_state={},
                    conversation_summary="",
                    resolver=resolver,
                    retrieval_query=q,
                )
                return package

        with assistant_step_span(assistant_scope, "session_context.load_thread") as thread_out:
            thread_state, conversation_summary = load_session_thread(db, scope=scope, session_key=sk)
            thread_out["summary_chars"] = len(conversation_summary or "")

        if session_message_index_enabled() and turns:
            with assistant_step_span(assistant_scope, "session_context.index_sync") as idx_out:
                try:
                    index_session_turns(db, scope=scope, session_key=sk, turns=turns)
                    idx_out["indexed"] = True
                except Exception as exc:
                    logger.debug("session index sync failed: %s", exc)
                    idx_out["error"] = str(exc)[:200]

        search_hits: List[RelevantTurn] = []
        if q and session_message_index_enabled():
            with assistant_step_span(
                assistant_scope,
                "session_context.semantic_search",
                input_payload={"query_chars": len(q)},
            ) as search_out:
                try:
                    search_hits = search_session_messages(
                        db, scope=scope, session_key=sk, query=q, k=_max_relevant_turns() + 3
                    )
                    search_out["hits_count"] = len(search_hits)
                except Exception as exc:
                    logger.debug("session search failed: %s", exc)
                    search_out["error"] = str(exc)[:200]

        with assistant_step_span(assistant_scope, "session_context.resolver") as resolver_out:
            tc_kind = (
                str((turn_context or {}).get("referential_kind") or "none").strip().lower()
                if isinstance(turn_context, dict)
                else "none"
            )
            if tc_kind != "none":
                from app.services.chat.turn_context_resolution import (
                    TurnContextResolution,
                    load_prior_turn_evidence_from_turns,
                    session_result_from_turn_context,
                )

                resolution = (
                    TurnContextResolution.from_dict(turn_context)
                    if isinstance(turn_context, dict)
                    else None
                )
                prior = load_prior_turn_evidence_from_turns(turns)
                resolver = session_result_from_turn_context(
                    resolution,  # type: ignore[arg-type]
                    prior_evidence=prior,
                )
                resolver_out["turn_context"] = tc_kind
            else:
                resolver = resolve_turn_semantic(
                    question=q,
                    turns=turns,
                    search_hits=search_hits,
                    trace_scope=assistant_scope,
                    primary_intent=primary_intent,
                    intent_confidence=intent_confidence,
                    turn_context=turn_context,
                )
            resolver = enrich_resolver_with_session_signals(
                resolver, question=q, turns=turns, search_hits=search_hits
            )
            resolver = apply_session_turn_contract(
                resolver, question=q, turns=turns, turn_context=turn_context
            )
            resolver = apply_corpus_retrieval_policy(
                resolver,
                question=q,
                task_type=task_type,
                corpus_size=corpus_size,
                draft_mode=draft_mode,
            )
            resolver_out["turn_relation"] = resolver.turn_relation.value
            resolver_out["needs_document_retrieval"] = resolver.needs_document_retrieval
            resolver_out["confidence"] = resolver.confidence

        relevant = _merge_relevant_turns(search_hits, turns, resolver.anchor_message_ids)

        with assistant_step_span(assistant_scope, "session_context.evidence_replay") as replay_out:
            evidence_replay = _try_evidence_replay(turns, resolver, search_hits)
            replay_out["has_replay"] = evidence_replay is not None
            if evidence_replay is not None:
                replay_out["resolution_kind"] = getattr(evidence_replay, "resolution_kind", "")

        last_assistant = find_last_assistant_turn(turns)
        prior_mid = last_assistant.message_id if last_assistant else ""
        prior_excerpt = ((last_assistant.content or "").strip()[:1800] if last_assistant else "")

        prompt_parts: List[str] = []
        thread_block = format_thread_state_block(thread_state, conversation_summary)
        if thread_block:
            prompt_parts.append(thread_block)
        rel_block = _format_relevant_turns_block(relevant)
        if rel_block:
            prompt_parts.append(rel_block)
        if resolver.focus and resolver.turn_relation is not TurnRelation.NEW_TOPIC:
            prompt_parts.append(
                f"=== ФОКУС ТЕКУЩЕГО ЗАПРОСА ===\n{resolver.focus}\n"
                f"(связь с диалогом: {resolver.turn_relation.value}, уверенность: {resolver.confidence:.2f})"
            )

        if resolver.prefers_memory_only and prior_excerpt:
            prompt_parts.append(
                "=== РЕЖИМ: ОТВЕТ ИЗ ПАМЯТИ ЧАТА (БЕЗ НОВОГО ПОИСКА ПО ДОКУМЕНТАМ) ===\n"
                "Используй только переписку и блок якоря ниже. Не добавляй факты, которых не было в чате."
            )
            prompt_parts.append(
                "=== ПРЕДЫДУЩИЙ ОТВЕТ АССИСТЕНТА (ЯКОРЬ) ===\n"
                f"[{prior_mid or 'unknown'}]\n{prior_excerpt}"
            )

        prompt_block = "\n\n".join(prompt_parts)

        package = SessionContextPackage(
            scope=scope,
            session_key=sk,
            prompt_block=prompt_block,
            thread_state=thread_state,
            conversation_summary=conversation_summary,
            resolver=resolver,
            relevant_turns=relevant,
            evidence_replay=evidence_replay,
            prior_answer_available=bool(last_assistant),
            prior_answer_message_id=prior_mid,
            prior_answer_excerpt=prior_excerpt,
        )
        result = attach_retrieval_query(package, q)
        if isinstance(turn_context, dict) and turn_context.get("referential_kind") not in (
            None,
            "none",
        ):
            standalone = str(turn_context.get("standalone_query") or "").strip()
            if standalone:
                result.retrieval_query = standalone
        root_out["prompt_chars"] = len(result.prompt_block or "")
        root_out["has_evidence_replay"] = result.evidence_replay is not None
        return result


def _try_evidence_replay(
    turns: List[SessionMessageTurn],
    resolver,
    search_hits: List[RelevantTurn],
) -> Optional[object]:
    """Transcript replay for clarify_prior (prior assistant text; citations optional)."""
    target = resolve_replay_target(turns, resolver, search_hits)
    if target is None:
        return None
    return build_evidence_anchor_reply(
        message_id=target.message_id,
        content=target.content,
        evidence=target.evidence,
        focus=resolver.focus,
        resolution_kind=target.resolution_kind,
    )


def refresh_session_context_after_turn(
    db: Session,
    *,
    scope: Scope,
    session_id: str,
    case_id: Optional[str] = None,
    last_user: str = "",
    last_assistant: str = "",
) -> None:
    """Update thread state + index after assistant message persisted."""
    if not session_context_enabled():
        return

    if scope == "case":
        sk = case_session_key(case_id or "", session_id)
        if not sk or is_editor_session_id(session_id):
            return
        turns = load_case_session_turns(db, case_id=case_id or "", session_id=session_id)
    else:
        sk = global_session_key(session_id)
        if not sk:
            return
        turns = load_global_session_turns(db, session_id=session_id)

    try:
        if session_message_index_enabled():
            index_session_turns(db, scope=scope, session_key=sk, turns=turns)
        update_thread_state_after_turn(
            db,
            scope=scope,
            session_key=sk,
            turns=turns,
            last_user=last_user,
            last_assistant=last_assistant,
        )
        db.commit()
    except Exception as exc:
        logger.warning("refresh_session_context_after_turn failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass


def _empty_package(scope: Scope, session_id: str, case_id: Optional[str]) -> SessionContextPackage:
    from app.services.chat.session_context_resolver import fallback_resolve

    sk = case_session_key(case_id or "", session_id) if scope == "case" else global_session_key(session_id)
    resolver = fallback_resolve("", [], [])
    package = SessionContextPackage(
        scope=scope,
        session_key=sk or "",
        prompt_block="",
        thread_state={},
        conversation_summary="",
        resolver=resolver,
    )
    return attach_retrieval_query(package, "")
