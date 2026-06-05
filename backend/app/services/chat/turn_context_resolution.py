"""
Step 0 — Turn Context Resolution (immutable contract per user turn).

Primary router: LLM judge with dialog transcript + prior evidence (referential_llm_judge).
Fallback: structural regex classifier (referential_classifier).
Phase 2: referential query resolver for scoped follow-ups when standalone_query not preset.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Sequence

from app.services.chat.referential_classifier import ReferentialKind
from app.services.chat.referential_llm_judge import ReferentialJudgeResult, classify_referential_kind_judge
from app.services.chat.referential_query_resolver import resolve_referential_query
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.standalone_query_resolver import resolve_standalone_query
from app.services.chat.turn_context_evidence import (
    PriorTurnEvidence,
    anchor_chunk_ids,
    load_prior_turn_evidence_from_turns,
    unique_inherited_file_ids,
)

# Re-export evidence types for callers/tests.
from app.services.chat.turn_context_evidence import CitationAnchor  # noqa: F401


@dataclass(frozen=True)
class TurnContextResolution:
    original_question: str
    standalone_query: str
    referential_kind: ReferentialKind
    inherited_file_ids: tuple[str, ...]
    anchor_chunk_ids: tuple[str, ...]
    suggested_intent: str | None
    needs_document_retrieval: bool
    prefer_parent_context: bool
    reason: str
    confidence: float
    query_resolver: str = "unchanged"
    routing_resolver: str = "unchanged"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TurnContextResolution:
        return cls(
            original_question=str(data.get("original_question") or ""),
            standalone_query=str(data.get("standalone_query") or ""),
            referential_kind=data.get("referential_kind") or "none",  # type: ignore[arg-type]
            inherited_file_ids=tuple(data.get("inherited_file_ids") or ()),
            anchor_chunk_ids=tuple(data.get("anchor_chunk_ids") or ()),
            suggested_intent=data.get("suggested_intent"),
            needs_document_retrieval=bool(data.get("needs_document_retrieval", True)),
            prefer_parent_context=bool(data.get("prefer_parent_context")),
            reason=str(data.get("reason") or ""),
            confidence=float(data.get("confidence") or 0.0),
            query_resolver=str(data.get("query_resolver") or "unchanged"),
            routing_resolver=str(data.get("routing_resolver") or "unchanged"),
        )


def _expand_standalone_query(
    *,
    question: str,
    kind: ReferentialKind,
    prior_evidence: PriorTurnEvidence | None,
    dialog_history: str,
    conversation_summary: str,
    anchor_filenames: Sequence[str],
    preset_standalone: str = "",
) -> tuple[str, str, float, str]:
    """Phase 2: standalone query for routing and retrieval."""
    preset = (preset_standalone or "").strip()
    if preset and len(preset) >= 4 and preset.lower() != (question or "").strip().lower():
        return preset, "llm_judge_standalone", 0.9, "llm_judge"

    if kind in {"scoped_deep_read", "citation_expand"}:
        ref = resolve_referential_query(
            question=question,
            prior_evidence=prior_evidence,
            referential_kind=kind,
        )
        confidence = 0.88 if ref.changed else 0.82
        reason = ref.reason if ref.changed else f"referential_{kind}"
        if ref.resolver == "llm":
            confidence = min(0.95, confidence + 0.05)
        return ref.standalone_query, reason, confidence, ref.resolver

    expanded = resolve_standalone_query(
        question,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )
    if expanded.changed:
        return expanded.resolved_question, expanded.reason, 0.7, "dialog_history"
    return question, "explicit_question", 0.5, "unchanged"


def _resolution_from_judge(
    *,
    original: str,
    judge: ReferentialJudgeResult,
    prior_evidence: PriorTurnEvidence | None,
    dialog_history: str,
    conversation_summary: str,
    anchor_filenames: Sequence[str],
) -> TurnContextResolution:
    kind = judge.referential_kind
    inherited: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()
    if prior_evidence is not None and kind != "none":
        inherited = unique_inherited_file_ids(prior_evidence)
        chunk_ids = anchor_chunk_ids(prior_evidence)

    routing_resolver = judge.resolver
    base_reason = judge.reason

    if kind == "memory_synthesis":
        return TurnContextResolution(
            original_question=original,
            standalone_query=original,
            referential_kind=kind,
            inherited_file_ids=inherited,
            anchor_chunk_ids=chunk_ids,
            suggested_intent="clarify_prior",
            needs_document_retrieval=False,
            prefer_parent_context=False,
            reason=f"referential_memory_synthesis;{base_reason}",
            confidence=judge.confidence,
            query_resolver="unchanged",
            routing_resolver=routing_resolver,
        )

    if kind == "citation_expand":
        standalone, reason, confidence, resolver = _expand_standalone_query(
            question=original,
            kind=kind,
            prior_evidence=prior_evidence,
            dialog_history=dialog_history,
            conversation_summary=conversation_summary,
            anchor_filenames=anchor_filenames,
            preset_standalone=judge.standalone_query,
        )
        return TurnContextResolution(
            original_question=original,
            standalone_query=standalone,
            referential_kind=kind,
            inherited_file_ids=inherited,
            anchor_chunk_ids=chunk_ids,
            suggested_intent="drill_down",
            needs_document_retrieval=True,
            prefer_parent_context=True,
            reason=f"referential_citation_expand;{reason};{base_reason}",
            confidence=max(judge.confidence, confidence),
            query_resolver=resolver,
            routing_resolver=routing_resolver,
        )

    if kind == "scoped_deep_read":
        standalone, reason, confidence, resolver = _expand_standalone_query(
            question=original,
            kind=kind,
            prior_evidence=prior_evidence,
            dialog_history=dialog_history,
            conversation_summary=conversation_summary,
            anchor_filenames=anchor_filenames,
            preset_standalone=judge.standalone_query,
        )
        return TurnContextResolution(
            original_question=original,
            standalone_query=standalone,
            referential_kind=kind,
            inherited_file_ids=inherited,
            anchor_chunk_ids=chunk_ids,
            suggested_intent="drill_down",
            needs_document_retrieval=True,
            prefer_parent_context=bool(chunk_ids),
            reason=f"referential_scoped_deep_read;{reason};{base_reason}",
            confidence=max(judge.confidence, confidence),
            query_resolver=resolver,
            routing_resolver=routing_resolver,
        )

    standalone, reason, confidence, resolver = _expand_standalone_query(
        question=original,
        kind="none",
        prior_evidence=None,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )
    return TurnContextResolution(
        original_question=original,
        standalone_query=standalone,
        referential_kind="none",
        inherited_file_ids=(),
        anchor_chunk_ids=(),
        suggested_intent=None,
        needs_document_retrieval=judge.needs_document_retrieval,
        prefer_parent_context=False,
        reason=f"{reason};{base_reason}",
        confidence=max(judge.confidence, confidence),
        query_resolver=resolver,
        routing_resolver=routing_resolver,
    )


def resolve_turn_context(
    *,
    question: str,
    prior_evidence: PriorTurnEvidence | None = None,
    turns: Sequence[SessionMessageTurn] = (),
    dialog_history: str = "",
    conversation_summary: str = "",
    anchor_filenames: Sequence[str] = (),
) -> TurnContextResolution:
    original = (question or "").strip()
    has_prior = prior_evidence is not None and bool(
        (prior_evidence.assistant_excerpt or "").strip()
    )

    judge = classify_referential_kind_judge(
        question=original,
        has_prior=has_prior,
        prior_evidence=prior_evidence,
        turns=turns,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )
    return _resolution_from_judge(
        original=original,
        judge=judge,
        prior_evidence=prior_evidence,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )


def resolver_hints_from_turn_context(
    resolution: TurnContextResolution,
) -> tuple[str, bool]:
    if resolution.referential_kind == "memory_synthesis":
        return "clarify_prior", False
    if resolution.referential_kind in {"citation_expand", "scoped_deep_read"}:
        return "follow_up", True
    return "follow_up", resolution.needs_document_retrieval


def session_result_from_turn_context(
    resolution: TurnContextResolution,
    *,
    prior_evidence: PriorTurnEvidence | None = None,
) -> "SessionResolveResult":
    from app.services.chat.session_context_types import SessionResolveResult, TurnRelation

    rel_hint, needs_docs = resolver_hints_from_turn_context(resolution)
    if rel_hint == "clarify_prior":
        rel = TurnRelation.CLARIFY_PRIOR
    elif rel_hint == "new_topic":
        rel = TurnRelation.NEW_TOPIC
    else:
        rel = TurnRelation.FOLLOW_UP

    anchor_ids: list[str] = []
    if prior_evidence and prior_evidence.message_id:
        anchor_ids.append(prior_evidence.message_id)

    return SessionResolveResult(
        turn_relation=rel,
        needs_document_retrieval=needs_docs,
        focus=resolution.original_question[:500],
        anchor_message_ids=anchor_ids[:3],
        confidence=resolution.confidence,
        rationale=f"turn_context_{resolution.referential_kind}",
    )


def load_and_resolve_turn_context(
    *,
    question: str,
    turns: Sequence[SessionMessageTurn],
    dialog_history: str = "",
    conversation_summary: str = "",
    anchor_filenames: Sequence[str] = (),
) -> TurnContextResolution:
    prior = load_prior_turn_evidence_from_turns(turns)
    return resolve_turn_context(
        question=question,
        prior_evidence=prior,
        turns=turns,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
    )
