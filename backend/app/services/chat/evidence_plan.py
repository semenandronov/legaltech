"""
Evidence plan — latency contract for one case-assistant turn.

Refines tier budget with intent-specific retrieval policy (rerank, rounds, scope).
Applied after execution_tier resolution; may only shrink budgets, never expand.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional

from app.config import config
from app.services.chat.case_assistant_intent import CaseAssistantIntent
from app.services.chat.execution_tier import attach_pipeline_budget_for_tier, build_tier_execution_contract

EvidenceMode = Literal[
    "chat_only",
    "case_metadata",
    "scoped_rag",
    "full_rag",
]

RetrievalPath = Literal[
    "chunk_hybrid",
    "scoped_deep_read",
    "summary_overview",
]

RerankTier = Literal[
    "none",
    "light",
    "heavy",
]


@dataclass(frozen=True)
class EvidencePlan:
    """Structured retrieval policy for one turn."""

    evidence_mode: EvidenceMode
    retrieval_path: RetrievalPath
    rerank_enabled: bool
    rerank_tier: RerankTier
    parent_context_enabled: bool
    max_retrieval_rounds: int
    rerank_pool_cap: int
    plan_reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _rerank_pool_cap_default() -> int:
    return max(8, int(getattr(config, "CASE_ASSISTANT_RERANK_POOL_CAP", 24) or 24))


def build_evidence_plan(
    *,
    intent: CaseAssistantIntent,
    execution_tier: str,
    rerank_enabled: bool,
    max_retrieval_rounds: int,
) -> EvidencePlan:
    """Derive evidence policy from product intent + execution tier."""
    primary = (intent.primary or "").strip().lower()
    tier = (execution_tier or "standard").strip().lower()

    if tier in {"no_retrieval", "clarify"}:
        return EvidencePlan(
            evidence_mode="chat_only",
            retrieval_path="chunk_hybrid",
            rerank_enabled=False,
            rerank_tier="none",
            parent_context_enabled=False,
            max_retrieval_rounds=0,
            rerank_pool_cap=_rerank_pool_cap_default(),
            plan_reason=f"tier_{tier}",
        )

    mode: EvidenceMode = "scoped_rag"
    retrieval_path: RetrievalPath = "chunk_hybrid"
    rerank = bool(rerank_enabled)
    rerank_tier: RerankTier = "light"
    parent_ctx = bool(getattr(config, "CASE_ASSISTANT_PARENT_CONTEXT_ENABLED", True))
    rounds = max(0, int(max_retrieval_rounds or 0))
    pool_cap = _rerank_pool_cap_default()
    reason = "tier_default"

    if primary == "case_corpus_overview":
        mode = "case_metadata"
        retrieval_path = "summary_overview"
        rerank = False
        rerank_tier = "none"
        parent_ctx = False
        rounds = min(rounds, 1)
        pool_cap = min(pool_cap, 40)
        reason = "overview_summary_first"
    elif primary in {"narrow_fact", "standard_case_qa"}:
        mode = "scoped_rag"
        rerank = True
        rerank_tier = "light"
        parent_ctx = False
        rounds = min(rounds, 1)
        pool_cap = min(pool_cap, 20)
        reason = "single_doc_or_fact"
    elif primary == "drill_down":
        mode = "scoped_rag"
        retrieval_path = "scoped_deep_read"
        rerank = True
        rerank_tier = "light"
        rounds = min(rounds, 1)
        pool_cap = min(pool_cap, 28)
        reason = "drill_down_bounded"
    elif primary in {"legal_analysis", "cross_doc_analysis"}:
        mode = "full_rag"
        rerank = True
        rerank_tier = "heavy"
        parent_ctx = True
        rounds = min(rounds, max(1, rounds))
        reason = "deep_analysis"

    if tier in {"deep", "mixed"} and primary != "case_corpus_overview":
        rerank = True
        rerank_tier = "heavy"
        parent_ctx = True

    if tier == "instant" and primary != "case_corpus_overview":
        parent_ctx = False
        rounds = min(rounds, 1)
        if rerank_tier != "none":
            rerank_tier = "light"

    if tier == "standard" and rerank_tier == "none" and primary not in {"case_corpus_overview"}:
        rerank = True
        rerank_tier = "light"

    return EvidencePlan(
        evidence_mode=mode,
        retrieval_path=retrieval_path,
        rerank_enabled=rerank,
        rerank_tier=rerank_tier,
        parent_context_enabled=parent_ctx,
        max_retrieval_rounds=rounds,
        rerank_pool_cap=pool_cap,
        plan_reason=reason,
    )


def apply_evidence_plan(
    profile: Dict[str, Any],
    *,
    intent: CaseAssistantIntent,
) -> Dict[str, Any]:
    """Merge evidence plan into budget profile and rebuild tier_contract."""
    out = dict(profile)
    plan = build_evidence_plan(
        intent=intent,
        execution_tier=str(out.get("execution_tier") or "standard"),
        rerank_enabled=bool(out.get("rerank_enabled")),
        max_retrieval_rounds=int(out.get("max_retrieval_rounds") or 0),
    )
    out["evidence_mode"] = plan.evidence_mode
    out["retrieval_path"] = plan.retrieval_path
    out["evidence_plan_reason"] = plan.plan_reason
    out["rerank_enabled"] = plan.rerank_enabled
    out["rerank_tier"] = plan.rerank_tier
    out["parent_context_enabled"] = plan.parent_context_enabled
    out["max_retrieval_rounds"] = plan.max_retrieval_rounds
    out["rerank_pool_cap"] = plan.rerank_pool_cap
    out["unified_retrieval"] = bool(getattr(config, "CASE_ASSISTANT_UNIFIED_RETRIEVAL", True))

    if plan.retrieval_path == "summary_overview":
        out["recall_k"] = 0
        max_sources = int(out.get("max_sources") or 0)
        out["final_k"] = max(3, min(max_sources, 20) if max_sources > 0 else 12)

    contract = build_tier_execution_contract(
        out,
        execution_tier=str(out.get("execution_tier") or "standard"),  # type: ignore[arg-type]
        tier_reason=str(out.get("tier_reason") or ""),
        response_shape=str(out.get("response_shape") or intent.response_shape),
        response_shape_reason=str(out.get("response_shape_reason") or intent.reason),
    )
    out["tier_contract"] = contract.to_dict()
    return out


def apply_turn_context_overrides(
    profile: Dict[str, Any],
    turn_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Honor immutable turn context contract — may only shrink retrieval, never expand."""
    if not isinstance(turn_context, dict):
        return profile

    kind = str(turn_context.get("referential_kind") or "none").strip().lower()
    if kind == "none":
        return profile

    out = dict(profile)
    if kind == "memory_synthesis" or not bool(turn_context.get("needs_document_retrieval", True)):
        tier_reason = (
            "turn_context_memory"
            if kind == "memory_synthesis"
            else "turn_context_no_retrieval"
        )
        out = attach_pipeline_budget_for_tier(
            out,
            "no_retrieval",
            tier_reason=tier_reason,
            response_shape=str(out.get("response_shape") or "brief"),
            response_shape_reason=str(out.get("response_shape_reason") or kind),
        )
        out["evidence_mode"] = "chat_only"
        out["retrieval_path"] = "chunk_hybrid"
        out["rerank_tier"] = "none"
        out["parent_context_enabled"] = False
        out["recall_k"] = 0
        out["max_retrieval_rounds"] = 0
        out["rerank_enabled"] = False
        out["turn_context_reason"] = str(turn_context.get("reason") or kind)
        return out

    inherited = turn_context.get("inherited_file_ids") or []
    if inherited:
        out["inherited_file_ids"] = list(inherited)
        out["anchor_file_ids"] = list(inherited)

    if bool(turn_context.get("prefer_parent_context")):
        out["parent_context_enabled"] = True

    if kind == "citation_expand":
        out["retrieval_path"] = "scoped_deep_read"
        out["parent_context_enabled"] = True
    elif kind == "scoped_deep_read" and str(out.get("retrieval_path") or "") == "chunk_hybrid":
        out["retrieval_path"] = "scoped_deep_read"

    anchor_chunks = turn_context.get("anchor_chunk_ids") or []
    if anchor_chunks:
        out["anchor_chunk_ids"] = list(anchor_chunks)

    out["turn_context_reason"] = str(turn_context.get("reason") or kind)
    return out
