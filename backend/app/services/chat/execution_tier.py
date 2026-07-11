"""
Execution tier resolution for in-case assistant adaptive RAG.

Authoritative tier contract: retrieval budgets + generation guardrails (hard caps).
Policy profiles may only shrink limits via min(), never expand them.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional, Tuple

from app.config import config

ExecutionTierLabel = Literal[
    "no_retrieval",
    "clarify",
    "instant",
    "standard",
    "deep",
    "mixed",
]

_NO_RETRIEVAL_RE = re.compile(
    r"^\s*(?:привет|здравствуй|добрый\s+(?:день|вечер|утро)|спасибо|благодарю|ок|окей|hello|hi|thanks)\s*[!.?]*\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TierExecutionContract:
    """Immutable runtime contract for one assistant turn."""

    execution_tier: str
    tier_reason: str
    primary_intent: str
    response_shape: str
    response_shape_reason: str
    recall_k: int
    final_k: int
    rerank_enabled: bool
    max_retrieval_rounds: int
    max_context_chars: int
    llm_max_tokens: int
    llm_temperature: float
    max_wall_time_ms: int
    budget_profile_name: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def adaptive_tier_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", True))


def _tier_recall_defaults() -> Dict[str, int]:
    return {
        "instant": int(getattr(config, "CASE_ASSISTANT_INSTANT_RECALL_K", 16) or 16),
        "standard": int(getattr(config, "CASE_ASSISTANT_STANDARD_RECALL_K", 35) or 35),
        "deep": int(getattr(config, "CASE_ASSISTANT_RECALL_K", 100) or 100),
        "mixed": int(getattr(config, "CASE_ASSISTANT_RECALL_K", 100) or 100),
    }


def _tier_generation_caps(execution_tier: ExecutionTierLabel) -> Tuple[int, int, float]:
    """Return (max_context_chars_cap, llm_max_tokens_cap, temperature) for tier."""
    tier = (execution_tier or "").strip().lower()
    ctx_caps = {
        "instant": int(getattr(config, "CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS", 3500) or 3500),
        "standard": int(
            getattr(config, "CASE_ASSISTANT_STANDARD_MAX_CONTEXT_CHARS", 48_000) or 48_000
        ),
        "deep": int(getattr(config, "CASE_ASSISTANT_DEEP_MAX_CONTEXT_CHARS", 64_000) or 64_000),
        "mixed": int(getattr(config, "CASE_ASSISTANT_DEEP_MAX_CONTEXT_CHARS", 64_000) or 64_000),
        "clarify": int(getattr(config, "CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS", 3500) or 3500),
        "no_retrieval": int(getattr(config, "CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS", 3500) or 3500),
    }
    tok_caps = {
        "instant": int(getattr(config, "CASE_ASSISTANT_INSTANT_MAX_TOKENS", 300) or 300),
        "standard": int(getattr(config, "CASE_ASSISTANT_STANDARD_MAX_TOKENS", 1500) or 1500),
        "deep": int(getattr(config, "CASE_ASSISTANT_DEEP_MAX_TOKENS", 4500) or 4500),
        "mixed": int(getattr(config, "CASE_ASSISTANT_DEEP_MAX_TOKENS", 4500) or 4500),
        "clarify": int(getattr(config, "CASE_ASSISTANT_INSTANT_MAX_TOKENS", 300) or 300),
        "no_retrieval": int(getattr(config, "CASE_ASSISTANT_INSTANT_MAX_TOKENS", 300) or 300),
    }
    temps = {
        "instant": float(getattr(config, "CASE_ASSISTANT_INSTANT_TEMPERATURE", 0.1) or 0.1),
        "standard": float(getattr(config, "CASE_ASSISTANT_STANDARD_TEMPERATURE", 0.2) or 0.2),
        "deep": float(getattr(config, "CASE_ASSISTANT_DEEP_TEMPERATURE", 0.3) or 0.3),
        "mixed": float(getattr(config, "CASE_ASSISTANT_DEEP_TEMPERATURE", 0.3) or 0.3),
        "clarify": 0.0,
        "no_retrieval": 0.1,
    }
    return (
        ctx_caps.get(tier, ctx_caps["standard"]),
        tok_caps.get(tier, tok_caps["standard"]),
        temps.get(tier, temps["standard"]),
    )


def _apply_tier_guardrails(out: Dict[str, Any], execution_tier: ExecutionTierLabel) -> None:
    """Cap profile limits by tier matrix — profile may only shrink, never expand."""
    ctx_cap, tok_cap, _temp = _tier_generation_caps(execution_tier)
    abs_ctx_ceiling = int(getattr(config, "CASE_ASSISTANT_MAX_CONTEXT_CHARS_CEILING", 48_000) or 48_000)
    ctx_cap = min(ctx_cap, max(1200, abs_ctx_ceiling))

    profile_ctx = int(out.get("max_context_chars") or 0)
    if profile_ctx > 0:
        out["max_context_chars"] = min(profile_ctx, ctx_cap)
    else:
        out["max_context_chars"] = ctx_cap

    profile_tok = int(out.get("max_tokens") or 0)
    if profile_tok > 0:
        out["max_tokens"] = min(profile_tok, tok_cap)
    else:
        out["max_tokens"] = tok_cap


def build_tier_execution_contract(
    profile: Dict[str, Any],
    *,
    execution_tier: ExecutionTierLabel,
    tier_reason: str,
    response_shape: str,
    response_shape_reason: str,
) -> TierExecutionContract:
    """Materialize authoritative contract from finalized budget profile."""
    _, _, temperature = _tier_generation_caps(execution_tier)
    return TierExecutionContract(
        execution_tier=str(execution_tier),
        tier_reason=str(tier_reason or ""),
        primary_intent=str(profile.get("primary_intent") or ""),
        response_shape=str(response_shape or "fact"),
        response_shape_reason=str(response_shape_reason or ""),
        recall_k=int(profile.get("recall_k") or 0),
        final_k=int(profile.get("final_k") or 0),
        rerank_enabled=bool(profile.get("rerank_enabled")),
        max_retrieval_rounds=int(profile.get("max_retrieval_rounds") or 0),
        max_context_chars=int(profile.get("max_context_chars") or 0),
        llm_max_tokens=int(profile.get("max_tokens") or 0),
        llm_temperature=temperature,
        max_wall_time_ms=int(profile.get("max_wall_time_ms") or 0),
        budget_profile_name=str(profile.get("name") or ""),
    )


def llm_max_tokens_from_budget(budget_profile: Optional[Dict[str, Any]]) -> int:
    """Single entry point for generation guardrail token cap."""
    if not isinstance(budget_profile, dict):
        return 0
    contract = budget_profile.get("tier_contract")
    if isinstance(contract, dict):
        cap = int(contract.get("llm_max_tokens") or 0)
        if cap > 0:
            return cap
    return int(budget_profile.get("max_tokens") or 0)


def infer_execution_tier_heuristic(
    *,
    question: str,
    task_type: str,
    depth_tier: str,
    clarification_needed: bool = False,
    legal_research: bool = False,
    court_practice: bool = False,
    deep_think: bool = False,
    draft_mode: bool = False,
    primary_intent: str = "",
) -> Tuple[ExecutionTierLabel, str]:
    """Heuristic tier from policy fields + resolved primary_intent (no LLM)."""
    q = (question or "").strip()
    if draft_mode:
        return "deep", "draft_mode"
    if court_practice and not legal_research:
        return "standard", "court_practice_toggle"
    if legal_research and not court_practice:
        return "standard", "legal_research_toggle"
    if legal_research:
        return "mixed", "legal_research_toggle"
    if deep_think:
        return "deep", "deep_think_enabled"

    if clarification_needed or task_type == "clarification":
        return "clarify", "clarification_needed"
    if not q:
        return "clarify", "empty_question"
    if _NO_RETRIEVAL_RE.match(q):
        return "no_retrieval", "greeting_or_thanks"

    tt = (task_type or "").strip().lower()
    dt = (depth_tier or "").strip().lower()
    intent = (primary_intent or "").strip().lower()

    if intent == "narrow_fact" or tt == "fact_lookup":
        return "instant", "intent_narrow_fact" if intent == "narrow_fact" else "task_fact_lookup"

    if intent == "drill_down":
        return "standard", "intent_drill_down"

    if intent == "case_corpus_overview" and dt == "fast":
        return "standard", "intent_case_corpus_overview_summary"

    if intent == "case_corpus_overview":
        return "deep", "intent_case_corpus_overview_deep"

    if intent == "standard_case_qa" and dt == "fast":
        return "instant", "intent_standard_case_qa_fast"

    if tt == "multi_doc_synthesis" and dt == "fast":
        return "instant", "multi_doc_overview_fast"
    if tt in {"multi_doc_synthesis", "contradiction_check"}:
        return "deep", f"task_{tt}"
    if tt == "legal_reasoning" and dt == "deep":
        return "deep", "task_legal_reasoning_deep"

    if dt == "fast" and tt == "single_doc_extraction":
        return "instant", "single_doc_instant"
    if dt == "fast" and tt == "legal_reasoning":
        return "standard", "legal_reasoning_fast"
    if dt == "deep":
        return "deep", "depth_deep"

    return "standard", "default_standard"


def attach_pipeline_budget_for_tier(
    profile: Dict[str, Any],
    execution_tier: ExecutionTierLabel,
    *,
    response_shape: str = "fact",
    response_shape_reason: str = "",
    tier_reason: str = "",
    primary_intent: str = "",
) -> Dict[str, Any]:
    """Apply recall/rerank rounds and authoritative generation guardrails."""
    out = dict(profile)
    recalls = _tier_recall_defaults()
    final_default = int(getattr(config, "CASE_ASSISTANT_FINAL_K", 15) or 15)
    max_sources = int(out.get("max_sources") or 15)

    if not adaptive_tier_enabled():
        out["recall_k"] = int(getattr(config, "CASE_ASSISTANT_RECALL_K", 100) or 100)
        out["final_k"] = min(max_sources, final_default) if max_sources > 0 else final_default
        out["rerank_enabled"] = bool(getattr(config, "CASE_ASSISTANT_RERANK_ENABLED", True))
        out["execution_tier"] = execution_tier
        out["max_retrieval_rounds"] = int(getattr(config, "CASE_ASSISTANT_MAX_RETRIEVAL_ROUNDS", 2) or 2)
        _apply_tier_guardrails(out, execution_tier)
    else:
        tier = execution_tier
        if tier == "no_retrieval":
            out["recall_k"] = 0
            out["final_k"] = 0
            out["rerank_enabled"] = False
            out["max_retrieval_rounds"] = 0
        elif tier == "clarify":
            out["recall_k"] = 0
            out["final_k"] = 0
            out["rerank_enabled"] = False
            out["max_retrieval_rounds"] = 0
        elif tier == "instant":
            out["recall_k"] = recalls["instant"]
            out["final_k"] = min(6, max_sources) if max_sources > 0 else 6
            out["rerank_enabled"] = False
            out["max_retrieval_rounds"] = 1
        elif tier == "standard":
            out["recall_k"] = recalls["standard"]
            out["final_k"] = min(10, max_sources) if max_sources > 0 else min(10, final_default)
            out["rerank_enabled"] = bool(getattr(config, "CASE_ASSISTANT_RERANK_ENABLED", True))
            out["max_retrieval_rounds"] = int(
                getattr(config, "CASE_ASSISTANT_STANDARD_MAX_RETRIEVAL_ROUNDS", 1) or 1
            )
        else:
            out["recall_k"] = recalls.get(tier, recalls["deep"])
            out["final_k"] = min(max_sources, final_default) if max_sources > 0 else final_default
            out["rerank_enabled"] = bool(getattr(config, "CASE_ASSISTANT_RERANK_ENABLED", True))
            out["max_retrieval_rounds"] = int(
                getattr(config, "CASE_ASSISTANT_DEEP_MAX_RETRIEVAL_ROUNDS", 3) or 3
            )

        out["execution_tier"] = tier
        _apply_tier_guardrails(out, tier)

    out["primary_intent"] = (primary_intent or "").strip()

    contract = build_tier_execution_contract(
        out,
        execution_tier=execution_tier,
        tier_reason=tier_reason,
        response_shape=response_shape,
        response_shape_reason=response_shape_reason,
    )
    out["tier_contract"] = contract.to_dict()
    out["response_shape"] = response_shape
    out["response_shape_reason"] = response_shape_reason
    out["max_tokens"] = contract.llm_max_tokens
    out["max_context_chars"] = contract.max_context_chars
    return out


def resolve_execution_tier(
    *,
    question: str,
    task_type: str,
    depth_tier: str,
    clarification_needed: bool = False,
    legal_research: bool = False,
    court_practice: bool = False,
    deep_think: bool = False,
    draft_mode: bool = False,
    structured_tier: Optional[str] = None,
    primary_intent: str = "",
) -> Tuple[ExecutionTierLabel, str]:
    """Resolve tier: optional LLM structured override, else heuristic."""
    if structured_tier in {
        "no_retrieval",
        "clarify",
        "instant",
        "standard",
        "deep",
        "mixed",
    }:
        return structured_tier, "structured_classifier"  # type: ignore[return-value]

    return infer_execution_tier_heuristic(
        question=question,
        task_type=task_type,
        depth_tier=depth_tier,
        clarification_needed=clarification_needed,
        legal_research=legal_research,
        court_practice=court_practice,
        deep_think=deep_think,
        draft_mode=draft_mode,
        primary_intent=primary_intent,
    )


def tier_skips_retrieval(execution_tier: Optional[str]) -> bool:
    return (execution_tier or "") in {"no_retrieval", "clarify"}


def escalate_tier(execution_tier: ExecutionTierLabel) -> ExecutionTierLabel:
    order = ["instant", "standard", "deep", "mixed"]
    if execution_tier not in order:
        return execution_tier
    idx = order.index(execution_tier)
    if idx < len(order) - 1:
        return order[idx + 1]  # type: ignore[return-value]
    return execution_tier


# Backward-compatible alias (tests / imports)
_apply_tier_context_ceiling = _apply_tier_guardrails
