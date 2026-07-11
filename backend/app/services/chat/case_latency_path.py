"""
Case assistant latency path — first-class Adaptive RAG gate.

Decides FAST vs HEAVY before expensive prep LLMs run.

Product default (draft / 127-FZ / deep off): most turns are document Q&A
(+ optional court practice). Those must take the FAST path:

  embed → hybrid recall → generate

Heavy markers and UI toggles keep the full prep/graph stack.
(Rerank on FAST hurt golden hit-rate; keep skip until structural recall improves.)
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

from app.config import config
from app.services.chat.case_assistant_intent import (
    CaseAssistantIntent,
    extract_query_features,
    resolve_case_assistant_intent,
)
from app.services.chat.execution_tier import _NO_RETRIEVAL_RE

LatencyPathKind = Literal["fast", "heavy", "memory", "no_retrieval"]

_HEAVY_PRIMARY = frozenset(
    {
        "drafting",
        "contradiction",
        "cross_doc_analysis",
        "legal_analysis",
    }
)

_HEAVY_TASK_TYPES = frozenset(
    {
        "drafting",
        "contradiction_check",
    }
)


def latency_path_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_LATENCY_PATH_ENABLED", True))


@dataclass(frozen=True)
class CaseLatencyPath:
    """Immutable per-turn latency contract."""

    kind: LatencyPathKind
    reason: str
    skip_turn_context_llm: bool
    skip_structured_data_router: bool
    skip_llm_document_scope: bool
    skip_session_semantic: bool
    skip_tier_llm: bool
    force_execution_tier: Optional[str]
    max_retrieval_rounds: int
    rerank_policy: Literal["skip", "light_only", "default"]
    compact_generation: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def is_fast(self) -> bool:
        return self.kind == "fast"

    @property
    def is_heavy(self) -> bool:
        return self.kind == "heavy"


def _fast_path(*, reason: str) -> CaseLatencyPath:
    # Deterministic №-ref still wins inside the router; this only gates the
    # cheap catalog LLM (yandexgpt-lite) for file-scope when refs miss.
    allow_fast_llm_scope = bool(
        getattr(config, "CASE_ASSISTANT_FAST_LLM_FILE_SCOPE_ENABLED", True)
    )
    return CaseLatencyPath(
        kind="fast",
        reason=reason,
        skip_turn_context_llm=True,
        skip_structured_data_router=True,
        skip_llm_document_scope=not allow_fast_llm_scope,
        skip_session_semantic=True,
        skip_tier_llm=True,
        force_execution_tier="instant",
        max_retrieval_rounds=2,  # round0 + one deterministic escalate (broaden/deepen)
        rerank_policy="skip",
        compact_generation=True,
    )


def _heavy_path(*, reason: str) -> CaseLatencyPath:
    return CaseLatencyPath(
        kind="heavy",
        reason=reason,
        skip_turn_context_llm=False,
        skip_structured_data_router=False,
        skip_llm_document_scope=False,
        skip_session_semantic=False,
        skip_tier_llm=False,
        force_execution_tier=None,
        max_retrieval_rounds=0,  # leave to tier budget
        rerank_policy="default",
        compact_generation=False,
    )


def _memory_path(*, reason: str) -> CaseLatencyPath:
    return CaseLatencyPath(
        kind="memory",
        reason=reason,
        skip_turn_context_llm=True,
        skip_structured_data_router=True,
        skip_llm_document_scope=True,
        skip_session_semantic=True,
        skip_tier_llm=True,
        force_execution_tier="no_retrieval",
        max_retrieval_rounds=0,
        rerank_policy="skip",
        compact_generation=True,
    )


def _no_retrieval_path(*, reason: str) -> CaseLatencyPath:
    return CaseLatencyPath(
        kind="no_retrieval",
        reason=reason,
        skip_turn_context_llm=True,
        skip_structured_data_router=True,
        skip_llm_document_scope=True,
        skip_session_semantic=True,
        skip_tier_llm=True,
        force_execution_tier="no_retrieval",
        max_retrieval_rounds=0,
        rerank_policy="skip",
        compact_generation=True,
    )


def _intent_requests_heavy(intent: CaseAssistantIntent) -> bool:
    if intent.primary in _HEAVY_PRIMARY:
        return True
    if intent.task_type in _HEAVY_TASK_TYPES:
        return True
    # Deep multi-doc synthesis (not the fast overview / summary path).
    if intent.task_type == "multi_doc_synthesis" and intent.depth_tier == "deep":
        return True
    if intent.task_type == "legal_reasoning" and intent.depth_tier == "deep":
        return True
    return False


def resolve_case_latency_path(
    *,
    question: str,
    draft_mode: bool = False,
    deep_think: bool = False,
    legal_research: bool = False,
    court_practice: bool = False,
    attached_files_count: int = 0,
    corpus_size: int = 0,
    intent: Optional[CaseAssistantIntent] = None,
    referential_kind: str = "none",
) -> CaseLatencyPath:
    """
    Resolve latency path without network calls.

    ``court_practice`` alone does not force HEAVY — practice retrieval stays
    on the FAST prep path (parallel graph node), matching product defaults.
    """
    if not latency_path_enabled():
        return _heavy_path(reason="latency_path_disabled")

    q = (question or "").strip()
    if not q:
        return _no_retrieval_path(reason="empty_question")
    if _NO_RETRIEVAL_RE.match(q):
        return _no_retrieval_path(reason="greeting_or_thanks")

    # UI overrides — explicit user request for heavy stack.
    if draft_mode:
        return _heavy_path(reason="ui_draft_mode")
    if deep_think:
        return _heavy_path(reason="ui_deep_think")
    if legal_research:
        return _heavy_path(reason="ui_legal_research")

    kind = (referential_kind or "none").strip().lower()
    if kind == "memory_synthesis":
        return _memory_path(reason="referential_memory_synthesis")

    resolved = intent
    if resolved is None:
        resolved = resolve_case_assistant_intent(
            question=q,
            attached_files_count=attached_files_count,
            corpus_size=corpus_size,
            draft_mode=draft_mode,
            legal_research=legal_research,
            deep_think=deep_think,
        )

    if resolved.clarification_needed or resolved.primary in {"empty", "too_short", "needs_clarification"}:
        return _no_retrieval_path(reason=f"clarify:{resolved.reason}")

    if _intent_requests_heavy(resolved):
        return _heavy_path(reason=f"intent:{resolved.primary}:{resolved.reason}")

    # Default bias: document Q&A (+ optional court practice) → FAST.
    suffix = "+court_practice" if court_practice else ""
    features = extract_query_features(
        question=q,
        attached_files_count=attached_files_count,
        corpus_size=corpus_size,
        draft_mode=draft_mode,
        legal_research=legal_research,
        deep_think=deep_think,
    )
    if resolved.primary == "narrow_fact" or resolved.task_type == "fact_lookup":
        return _fast_path(reason=f"fact_qa{suffix}:{resolved.reason}")
    if features.attached_files_count > 0:
        return _fast_path(reason=f"attached_scope{suffix}:{resolved.reason}")
    return _fast_path(reason=f"default_document_qa{suffix}:{resolved.primary}")


def apply_latency_path_to_budget(
    budget_profile: Dict[str, Any],
    path: CaseLatencyPath,
) -> Dict[str, Any]:
    """Merge latency contract into budget (may only tighten retrieval/generation)."""
    out = dict(budget_profile or {})
    out["latency_path"] = path.to_dict()
    out["skip_llm_document_scope"] = bool(path.skip_llm_document_scope)
    out["skip_session_semantic"] = bool(path.skip_session_semantic)

    if path.force_execution_tier:
        from app.services.chat.execution_tier import attach_pipeline_budget_for_tier

        out = attach_pipeline_budget_for_tier(
            out,
            path.force_execution_tier,  # type: ignore[arg-type]
            tier_reason=f"latency_path:{path.reason}",
            response_shape=str(out.get("response_shape") or "fact"),
            response_shape_reason="latency_path",
            primary_intent=str(out.get("primary_intent") or ""),
        )

    if path.max_retrieval_rounds > 0:
        current = int(out.get("max_retrieval_rounds") or path.max_retrieval_rounds)
        out["max_retrieval_rounds"] = min(current, path.max_retrieval_rounds)

    if path.rerank_policy == "skip":
        out["rerank_enabled"] = False
        out["rerank_tier"] = "none"
    elif path.rerank_policy == "light_only":
        # Must force-enable: instant tier budget sets rerank_enabled=False first.
        out["rerank_tier"] = "light"
        out["rerank_enabled"] = True
    # "default" — leave tier budget / query-plan decisions as-is.

    if path.compact_generation:
        out["generation_profile"] = "draft"
        out["compact_system_prompt"] = True
        # Same answer model; shrink prompt/output only (TTFT).
        # Dedicated FAST ceilings so legacy INSTANT=16k env cannot undo this.
        ctx_cap = int(
            getattr(config, "CASE_ASSISTANT_FAST_GEN_MAX_CONTEXT_CHARS", 3500) or 3500
        )
        tok_cap = int(getattr(config, "CASE_ASSISTANT_FAST_GEN_MAX_TOKENS", 300) or 300)
        cur_ctx = int(out.get("max_context_chars") or ctx_cap)
        cur_tok = int(out.get("max_tokens") or tok_cap)
        out["max_context_chars"] = max(1200, min(cur_ctx, ctx_cap))
        out["max_tokens"] = max(64, min(cur_tok, tok_cap))
        contract = out.get("tier_contract")
        if isinstance(contract, dict):
            contract = dict(contract)
            contract["max_context_chars"] = out["max_context_chars"]
            contract["llm_max_tokens"] = out["max_tokens"]
            out["tier_contract"] = contract

    return out
