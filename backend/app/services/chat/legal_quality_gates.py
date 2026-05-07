"""
Centralized legal quality gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.services.chat.conversation_policy_service import RunContext


@dataclass
class GateResult:
    allowed: bool
    status: str
    message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class LegalQualityGates:
    PROFILE_CITATION_POLICY: Dict[str, str] = {
        "retrieval_profile": "required",
        "extraction_profile": "best_effort",
        "legal_qna_profile": "required",
        "mixed_profile": "required",
        "legacy_default": "required",
    }

    @staticmethod
    def scope_gate(run_ctx: RunContext) -> GateResult:
        if run_ctx.scope == "case" and not run_ctx.case_id:
            return GateResult(
                allowed=False,
                status="scope_blocked",
                message="Нет контекста дела для ответа в режиме case.",
            )
        return GateResult(allowed=True, status="scope_ok")

    @staticmethod
    def citation_gate(
        run_ctx: RunContext,
        citations: List[Dict[str, Any]],
        *,
        prompt_profile_id: Optional[str] = None,
    ) -> GateResult:
        citation_policy = run_ctx.citation_policy
        if prompt_profile_id:
            citation_policy = LegalQualityGates.PROFILE_CITATION_POLICY.get(
                prompt_profile_id,
                citation_policy,
            )
        if citation_policy != "required":
            return GateResult(allowed=True, status="citations_best_effort")
        if citations:
            return GateResult(allowed=True, status="citations_ok", metadata={"citations_count": len(citations)})
        return GateResult(
            allowed=False,
            status="clarify_required",
            message="Недостаточно подтвержденных источников. Уточните запрос или добавьте документы.",
        )

    @staticmethod
    def confidence_gate(
        run_ctx: RunContext,
        *,
        confidence_score: Optional[float] = None,
        retrieval_hits: Optional[int] = None,
        prompt_profile_id: Optional[str] = None,
    ) -> GateResult:
        # Conservative default for legal flows.
        low_conf_threshold = 0.45
        if prompt_profile_id == "extraction_profile":
            low_conf_threshold = 0.35
        if confidence_score is not None and confidence_score < low_conf_threshold:
            return GateResult(
                allowed=False,
                status="clarify_required",
                message="Недостаточная уверенность для юридически безопасного ответа. Нужны уточнения.",
            )
        if retrieval_hits is not None and retrieval_hits <= 0 and run_ctx.mode in {"research", "case_advice", "comparison"}:
            return GateResult(
                allowed=False,
                status="clarify_required",
                message="Не найдено релевантных оснований в источниках. Уточните запрос.",
            )
        return GateResult(allowed=True, status="confidence_ok")

    @staticmethod
    def budget_gate(
        *,
        budget_profile: Optional[Dict[str, Any]] = None,
        wall_time_ms: Optional[int] = None,
        tool_calls: Optional[int] = None,
        llm_calls: Optional[int] = None,
    ) -> GateResult:
        profile = budget_profile or {}
        max_wall = int(profile.get("max_wall_time_ms") or 0)
        max_tool = int(profile.get("max_tool_calls") or 0)
        max_llm = int(profile.get("max_llm_calls") or 0)
        if max_wall > 0 and wall_time_ms is not None and wall_time_ms > max_wall:
            return GateResult(
                allowed=False,
                status="budget_exceeded",
                message=f"Превышен лимит времени выполнения ({wall_time_ms}ms > {max_wall}ms).",
                metadata={"budget_type": "wall_time_ms", "actual": wall_time_ms, "limit": max_wall},
            )
        if max_tool > 0 and tool_calls is not None and tool_calls > max_tool:
            return GateResult(
                allowed=False,
                status="budget_exceeded",
                message=f"Превышен лимит вызовов инструментов ({tool_calls} > {max_tool}).",
                metadata={"budget_type": "tool_calls", "actual": tool_calls, "limit": max_tool},
            )
        if max_llm > 0 and llm_calls is not None and llm_calls > max_llm:
            return GateResult(
                allowed=False,
                status="budget_exceeded",
                message=f"Превышен лимит LLM-вызовов ({llm_calls} > {max_llm}).",
                metadata={"budget_type": "llm_calls", "actual": llm_calls, "limit": max_llm},
            )
        return GateResult(allowed=True, status="budget_ok")

