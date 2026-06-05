"""
In-thread dialog replay policy (Session Memory Contract).

When the user asks to repeat, narrow, or clarify a prior assistant answer in the
same chat, we answer from the persisted transcript (assistant message text) — not
a fresh RAG pass. Citations in evidence are optional (UI enrichment only).

Eligibility uses turn_relation (LLM or search-driven fallback) and prior assistant
turns with non-empty content. No phrase triggers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from app.config import config
from app.services.chat.case_metadata_service import is_case_metadata_question
from app.services.chat.evidence_bundle import evidence_citations
from app.services.chat.session_context_types import (
    RelevantTurn,
    SessionMessageTurn,
    SessionResolveResult,
    TurnRelation,
)


@dataclass(frozen=True)
class ReplayTarget:
    message_id: str
    content: str
    evidence: object
    resolution_kind: str


def turn_has_assistant_content(turn: SessionMessageTurn) -> bool:
    """Assistant turn with persisted answer text (in-chat memory anchor)."""
    if (turn.role or "").lower() != "assistant":
        return False
    return bool((turn.content or "").strip())


def find_last_assistant_turn(
    turns: Sequence[SessionMessageTurn],
) -> Optional[SessionMessageTurn]:
    for t in reversed(turns):
        if turn_has_assistant_content(t):
            return t
    return None


def turn_has_replayable_evidence(turn: SessionMessageTurn) -> bool:
    """Assistant turn with persisted citation bundle (optional UI enrichment)."""
    if (turn.role or "").lower() != "assistant":
        return False
    return bool(evidence_citations(turn.evidence))


def find_last_replayable_assistant(
    turns: Sequence[SessionMessageTurn],
) -> Optional[SessionMessageTurn]:
    for t in reversed(turns):
        if turn_has_replayable_evidence(t):
            return t
    return None


def normalize_user_question(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def is_repeated_user_question(
    question: str,
    turns: Sequence[SessionMessageTurn],
) -> bool:
    """Same user question already appears earlier in the thread — needs a fresh pass, not replay."""
    nq = normalize_user_question(question)
    if not nq:
        return False
    for t in turns:
        if (t.role or "").lower() != "user":
            continue
        if normalize_user_question(t.content) == nq:
            return True
    return False


def _has_severe_text_duplication(text: str) -> bool:
    """Detect double-stream / replay corruption (near-identical halves or repeated long runs)."""
    n = len(text)
    if n < 240:
        return False
    half = n // 2
    head = text[:half].strip()
    tail = text[half : half * 2].strip()
    if len(head) >= 120 and head == tail:
        return True
    window = min(80, max(40, n // 8))
    if window < 40:
        return False
    sample = text[:window]
    if len(sample) < 40:
        return False
    if text.count(sample) >= 3:
        return True
    return False


def assistant_text_replay_quality_ok(content: str) -> bool:
    """Structural quality gate before replaying persisted assistant text."""
    text = (content or "").strip()
    if len(text) < 20:
        return False
    if _has_severe_text_duplication(text):
        return False
    return True


_CORPUS_RETRIEVAL_TASKS = frozenset(
    {
        "multi_doc_synthesis",
        "single_doc_extraction",
        "contradiction_check",
        "legal_reasoning",
        "fact_lookup",
    }
)


def task_requires_corpus_retrieval(
    task_type: str | None,
    *,
    corpus_size: int = 0,
    draft_mode: bool = False,
) -> bool:
    if draft_mode or int(corpus_size or 0) <= 0:
        return False
    return (task_type or "").strip().lower() in _CORPUS_RETRIEVAL_TASKS


def apply_corpus_retrieval_policy(
    resolver: SessionResolveResult,
    *,
    question: str,
    task_type: str | None,
    corpus_size: int = 0,
    draft_mode: bool = False,
) -> SessionResolveResult:
    """
    Conversation policy is authoritative for corpus-backed answers.

    Session router may skip retrieval when chat memory looks sufficient, but
    tasks like multi_doc_synthesis must read indexed case files with citations.
    """
    if not task_requires_corpus_retrieval(task_type, corpus_size=corpus_size, draft_mode=draft_mode):
        return resolver
    if is_case_metadata_question(question):
        return resolver
    if resolver.needs_document_retrieval:
        return resolver

    rel = resolver.turn_relation
    if rel is TurnRelation.CLARIFY_PRIOR:
        rel = TurnRelation.FOLLOW_UP

    return SessionResolveResult(
        turn_relation=rel,
        needs_document_retrieval=True,
        focus=resolver.focus or question[:200],
        anchor_message_ids=list(resolver.anchor_message_ids),
        confidence=max(resolver.confidence, 0.7),
        rationale=((resolver.rationale or "")[:180] + "; corpus_task_requires_retrieval").strip("; "),
    )


def apply_session_turn_contract(
    resolver: SessionResolveResult,
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    turn_context: Optional[dict] = None,
) -> SessionResolveResult:
    """
    Normalize resolver output into replay/retrieval contract (structural, not phrase lists).
    """
    if isinstance(turn_context, dict):
        kind = str(turn_context.get("referential_kind") or "none").strip().lower()
        if kind == "memory_synthesis":
            return SessionResolveResult(
                turn_relation=TurnRelation.CLARIFY_PRIOR,
                needs_document_retrieval=False,
                focus=resolver.focus or question[:200],
                anchor_message_ids=list(resolver.anchor_message_ids),
                confidence=max(resolver.confidence, float(turn_context.get("confidence") or 0.9)),
                rationale=f"turn_context_{kind}",
            )
    if is_case_metadata_question(question):
        return SessionResolveResult(
            turn_relation=TurnRelation.FOLLOW_UP,
            needs_document_retrieval=False,
            focus=question[:200],
            anchor_message_ids=list(resolver.anchor_message_ids),
            confidence=max(resolver.confidence, 0.95),
            rationale="case_card_metadata",
        )

    if is_repeated_user_question(question, turns):
        return SessionResolveResult(
            turn_relation=TurnRelation.FOLLOW_UP,
            needs_document_retrieval=True,
            focus=resolver.focus or question[:200],
            anchor_message_ids=list(resolver.anchor_message_ids),
            confidence=max(resolver.confidence, 0.7),
            rationale=((resolver.rationale or "")[:200] + "; repeat_user_question").strip("; "),
        )

    if resolver.turn_relation is TurnRelation.NEW_TOPIC:
        if resolver.needs_document_retrieval:
            return resolver
        return SessionResolveResult(
            turn_relation=TurnRelation.NEW_TOPIC,
            needs_document_retrieval=True,
            focus=resolver.focus,
            anchor_message_ids=list(resolver.anchor_message_ids),
            confidence=resolver.confidence,
            rationale=((resolver.rationale or "")[:200] + "; new_topic_retrieval").strip("; "),
        )

    if (
        resolver.turn_relation is TurnRelation.CLARIFY_PRIOR
        and resolver.needs_document_retrieval
    ):
        return SessionResolveResult(
            turn_relation=TurnRelation.FOLLOW_UP,
            needs_document_retrieval=True,
            focus=resolver.focus or question[:200],
            anchor_message_ids=list(resolver.anchor_message_ids),
            confidence=resolver.confidence,
            rationale=((resolver.rationale or "")[:200] + "; clarify_requires_retrieval").strip("; "),
        )

    return resolver


def _search_score_min() -> float:
    return max(0.0, min(1.0, float(getattr(config, "SESSION_REPLAY_SEARCH_SCORE_MIN", 0.45) or 0.45)))


def _short_referential_question(question: str) -> bool:
    """Structural signal: brief turn likely pointing at prior context (not keyword lists)."""
    q = (question or "").strip()
    if not q:
        return False
    if len(q) > 280:
        return False
    words = q.split()
    return len(words) <= 24


def infer_clarify_from_session_signals(
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    search_hits: Sequence[RelevantTurn],
) -> bool:
    """
    Search- and thread-structure-driven clarify_prior inference (resolver fallback).

    True when semantic session search strongly matches a prior assistant answer
    and the thread already contains a prior assistant reply (transcript memory).

    Does NOT apply when the question needs scoped document retrieval (deictic /
    entity pointers) — those are handled by Turn Context Contract.
    """
    from app.services.chat.referential_classifier import (
        is_memory_synthesis_question,
        is_short_referential_question,
        needs_prior_turn_resolution,
    )

    if not is_short_referential_question(question):
        return False

    if is_memory_synthesis_question(question):
        return True

    if needs_prior_turn_resolution(question):
        return False

    if len(turns) < 2:
        return False

    last_assistant = find_last_assistant_turn(turns)
    if not last_assistant:
        return False

    # Structural fallback: when the immediately preceding persisted turn is an assistant
    # reply and the new user question is short, we treat it as a likely "clarify prior".
    # This avoids relying on session semantic search availability.
    last_turn = turns[-1] if turns else None
    if last_turn and (last_turn.role or "").lower() == "assistant":
        if last_turn.message_id == last_assistant.message_id:
            return True

    top = search_hits[0] if search_hits else None
    if top and (top.role or "").lower() == "assistant" and top.score >= _search_score_min():
        if top.message_id == last_assistant.message_id:
            return True
        if top.score >= 0.62:
            return True

    if len(turns) >= 2:
        prev = turns[-1]
        before = turns[-2]
        if (
            (prev.role or "").lower() == "user"
            and (before.role or "").lower() == "assistant"
            and before.message_id == last_assistant.message_id
        ):
            return True

    return False


def enrich_resolver_with_session_signals(
    resolver: SessionResolveResult,
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    search_hits: Sequence[RelevantTurn],
) -> SessionResolveResult:
    """
    Promote follow_up → clarify_prior when session search supports prior-answer replay.

    Does not downgrade new_topic or an explicit clarify_prior from the LLM.
    """
    if resolver.turn_relation is TurnRelation.NEW_TOPIC:
        return resolver
    if resolver.turn_relation is TurnRelation.CLARIFY_PRIOR:
        return resolver
    if not infer_clarify_from_session_signals(
        question=question, turns=turns, search_hits=search_hits
    ):
        return resolver

    anchor_ids = list(resolver.anchor_message_ids)
    top = search_hits[0] if search_hits else None
    if top and top.message_id not in anchor_ids:
        anchor_ids.insert(0, top.message_id)
    if not anchor_ids:
        last = find_last_assistant_turn(turns)
        if last:
            anchor_ids = [last.message_id]

    return SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        focus=resolver.focus or question[:200],
        anchor_message_ids=anchor_ids[:3],
        confidence=max(resolver.confidence, 0.55),
        rationale=(resolver.rationale or "")[:200] + "; session_search_clarify",
        needs_document_retrieval=False,
    )


def resolve_replay_target(
    turns: Sequence[SessionMessageTurn],
    resolver: SessionResolveResult,
    search_hits: Sequence[RelevantTurn],
) -> Optional[ReplayTarget]:
    """
    Pick the assistant turn to replay (anchors → search hit → latest with content).
    """
    if not resolver.should_replay_prior_answer:
        return None

    seen: set[str] = set()
    candidate_ids: List[str] = []

    for aid in resolver.anchor_message_ids:
        if aid and aid not in seen:
            seen.add(aid)
            candidate_ids.append(aid)

    for h in search_hits:
        if (h.role or "").lower() != "assistant":
            continue
        if h.message_id and h.message_id not in seen:
            seen.add(h.message_id)
            candidate_ids.append(h.message_id)

    for mid in candidate_ids:
        row = _find_turn(turns, mid)
        if row and turn_has_assistant_content(row):
            if not assistant_text_replay_quality_ok(row.content):
                continue
            return ReplayTarget(
                message_id=row.message_id,
                content=row.content,
                evidence=row.evidence,
                resolution_kind="transcript_clarify_prior",
            )

    last = find_last_assistant_turn(turns)
    if last and assistant_text_replay_quality_ok(last.content):
        return ReplayTarget(
            message_id=last.message_id,
            content=last.content,
            evidence=last.evidence,
            resolution_kind="transcript_clarify_prior_fallback",
        )
    return None


def _find_turn(turns: Sequence[SessionMessageTurn], message_id: str) -> Optional[SessionMessageTurn]:
    mid = (message_id or "").strip()
    if not mid:
        return None
    for t in turns:
        if t.message_id == mid:
            return t
    return None
