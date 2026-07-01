"""
Case query planner — production routing contract for in-case assistant.

Decides execution path, scope shortcuts, generation profile, and latency budgets
before LangGraph runs. Deterministic rules first; no extra LLM here.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from sqlalchemy.orm import Session

from app.config import config

logger = logging.getLogger(__name__)

ExecutionPath = Literal["evidence", "analytics", "synthesis", "memory_only"]
GenerationProfile = Literal["draft", "full"]
RerankPolicy = Literal["default", "skip", "light_only"]

_DRAFT_TASK_TYPES = frozenset(
    {
        "single_doc_extraction",
        "fact_lookup",
    }
)


def query_planner_enabled() -> bool:
    return bool(getattr(config, "CASE_ASSISTANT_QUERY_PLANNER_ENABLED", True))


def _default_deadlines_ms() -> Dict[str, int]:
    return {
        "document_scope_router": int(
            getattr(config, "CASE_ASSISTANT_SCOPE_ROUTER_DEADLINE_MS", 2500) or 2500
        ),
        "rerank": int(getattr(config, "CASE_ASSISTANT_RERANK_DEADLINE_MS", 1200) or 1200),
        "generation_ttft": int(
            getattr(config, "CASE_ASSISTANT_GENERATION_TTFT_BUDGET_MS", 3000) or 3000
        ),
    }


@dataclass(frozen=True)
class CaseQueryPlan:
    """Immutable per-turn routing plan."""

    path: ExecutionPath = "evidence"
    skip_document_scope_router: bool = False
    pre_retrieval_task: Optional[Dict[str, Any]] = None
    generation_profile: GenerationProfile = "full"
    compact_system_prompt: bool = False
    rerank_policy: RerankPolicy = "default"
    skip_session_semantic: bool = False
    deadline_ms: Dict[str, int] = field(default_factory=_default_deadlines_ms)
    plan_reason: str = "default"

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        if self.pre_retrieval_task is None:
            out.pop("pre_retrieval_task", None)
        return out


def _attached_ids(attached_file_ids: Optional[Sequence[str]]) -> List[str]:
    return [str(x).strip() for x in (attached_file_ids or []) if str(x).strip()]


def _build_pre_retrieval_task(
    *,
    search_query: str,
    file_ids: Sequence[str],
    scope_mode: str,
    rationale: str,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    return {
        "search_query": (search_query or "").strip(),
        "file_ids": list(file_ids),
        "scope_mode": scope_mode,
        "confidence": confidence,
        "rationale": rationale,
    }


def plan_case_query(
    *,
    db: Optional[Session] = None,
    case_id: str,
    question: str,
    retrieval_query: str = "",
    task_type: str = "",
    depth_tier: str = "",
    execution_tier: str = "",
    attached_file_ids: Optional[Sequence[str]] = None,
    structured_data_plane: Optional[str] = None,
    hybrid_rag_file_ids: Optional[Sequence[str]] = None,
    memory_only: bool = False,
    deep_think: bool = False,
    legal_research: bool = False,
) -> CaseQueryPlan:
    """
    Build routing plan without LLM calls.

    ``retrieval_query`` should match session resolver output when available.
    """
    if not query_planner_enabled():
        return CaseQueryPlan(plan_reason="planner_disabled")

    q = (question or "").strip()
    rq = (retrieval_query or q).strip()
    plane = (structured_data_plane or "rag").strip().lower()
    tier = (execution_tier or "standard").strip().lower()
    tt = (task_type or "").strip().lower()
    dt = (depth_tier or "").strip().lower()
    attached = _attached_ids(attached_file_ids)
    hybrid_rag = [str(x).strip() for x in (hybrid_rag_file_ids or []) if str(x).strip()]

    if memory_only:
        return CaseQueryPlan(
            path="memory_only",
            skip_document_scope_router=True,
            skip_session_semantic=True,
            generation_profile="draft",
            compact_system_prompt=True,
            rerank_policy="skip",
            plan_reason="memory_only_turn",
        )

    if plane == "sql":
        return CaseQueryPlan(
            path="analytics",
            skip_document_scope_router=True,
            skip_session_semantic=True,
            generation_profile="draft",
            compact_system_prompt=True,
            rerank_policy="skip",
            plan_reason="structured_data_sql",
        )

    if plane == "hybrid":
        pre_task = None
        if hybrid_rag:
            pre_task = _build_pre_retrieval_task(
                search_query=rq,
                file_ids=hybrid_rag,
                scope_mode="resolved",
                rationale="query_planner_hybrid_rag_scope",
            )
        return CaseQueryPlan(
            path="synthesis",
            skip_document_scope_router=bool(hybrid_rag),
            pre_retrieval_task=pre_task,
            generation_profile="full",
            compact_system_prompt=False,
            rerank_policy="light_only",
            plan_reason="structured_data_hybrid",
        )

    # --- evidence (document RAG) path ---
    pre_task: Optional[Dict[str, Any]] = None
    skip_scope = False
    reason_parts: List[str] = ["evidence"]

    if attached:
        skip_scope = True
        pre_task = _build_pre_retrieval_task(
            search_query=rq,
            file_ids=attached,
            scope_mode="attached",
            rationale="query_planner_attached_files",
            confidence=0.98,
        )
        reason_parts.append("attached_scope")

    use_draft = (
        not deep_think
        and not legal_research
        and tier in {"instant", "no_retrieval"}
        and (tt in _DRAFT_TASK_TYPES or (dt == "fast" and tt == "single_doc_extraction"))
    )
    if tier == "instant" and tt in _DRAFT_TASK_TYPES:
        use_draft = True
        reason_parts.append("instant_draft_gen")

    rerank_policy: RerankPolicy = "default"
    if tier == "instant":
        rerank_policy = "skip"
        reason_parts.append("instant_skip_rerank")
    elif use_draft:
        rerank_policy = "light_only"

    compact = use_draft and not deep_think

    # Skip heavy session semantic search on narrow scoped turns
    skip_semantic = bool(attached) or (use_draft and tier == "instant")

    return CaseQueryPlan(
        path="evidence",
        skip_document_scope_router=skip_scope,
        pre_retrieval_task=pre_task,
        generation_profile="draft" if use_draft else "full",
        compact_system_prompt=compact,
        rerank_policy=rerank_policy,
        skip_session_semantic=skip_semantic,
        plan_reason="+".join(reason_parts),
    )


def apply_query_plan_to_budget(
    budget_profile: Dict[str, Any],
    plan: CaseQueryPlan,
) -> Dict[str, Any]:
    """Merge planner decisions into budget profile (may only tighten, not expand)."""
    out = dict(budget_profile or {})
    out["query_plan"] = plan.to_dict()
    out["generation_profile"] = plan.generation_profile
    out["compact_system_prompt"] = plan.compact_system_prompt
    out["deadline_ms"] = dict(plan.deadline_ms)

    if plan.rerank_policy == "skip":
        out["rerank_enabled"] = False
        out["rerank_tier"] = "none"
    elif plan.rerank_policy == "light_only":
        out["rerank_tier"] = "light"

    return out


def generation_profile_from_state(state: Mapping[str, Any]) -> GenerationProfile:
    bp = state.get("budget_profile") if isinstance(state.get("budget_profile"), dict) else {}
    qp = state.get("query_plan") if isinstance(state.get("query_plan"), dict) else {}
    raw = str(
        qp.get("generation_profile")
        or bp.get("generation_profile")
        or "full"
    ).strip().lower()
    return "draft" if raw == "draft" else "full"


def use_compact_system_prompt(state: Mapping[str, Any]) -> bool:
    bp = state.get("budget_profile") if isinstance(state.get("budget_profile"), dict) else {}
    qp = state.get("query_plan") if isinstance(state.get("query_plan"), dict) else {}
    return bool(qp.get("compact_system_prompt") or bp.get("compact_system_prompt"))


def draft_generation_model_uri() -> str:
    explicit = (
        getattr(config, "CASE_ASSISTANT_DRAFT_GENERATION_MODEL", None)
        or ""
    ).strip()
    if explicit:
        return explicit
    router = (getattr(config, "CASE_ASSISTANT_ROUTER_MODEL", None) or "").strip()
    if router:
        return router
    folder = (getattr(config, "YANDEX_FOLDER_ID", None) or "").strip()
    if folder:
        return f"gpt://{folder}/yandexgpt-lite/latest"
    return "yandexgpt-lite/latest"


def create_case_generation_llm(
    state: Mapping[str, Any],
    *,
    streaming: bool = True,
    temperature: Optional[float] = None,
):
    """Pick draft (lite) or full model for answer generation."""
    from app.services.llm_factory import create_llm

    profile = generation_profile_from_state(state)
    if profile == "draft":
        temp = 0.1 if temperature is None else temperature
        return create_llm(
            model=draft_generation_model_uri(),
            temperature=temp,
            use_rate_limiting=False,
            streaming=streaming,
            cache_enabled=False,
        )
    temp = 0.1 if temperature is None else temperature
    return create_llm(
        temperature=temp,
        use_rate_limiting=False,
        streaming=streaming,
    )


def compact_evidence_system_prompt() -> str:
    return (
        "Ты юрист-аналитик по российскому праву. Ответь на вопрос только по материалам из контекста.\n"
        "Не выдумывай факты, даты и реквизиты. Если данных не хватает — скажи прямо.\n"
        "Маркеры [CHUNK:xxx] или [Dd:Cc] ставь сразу после смыслового фрагмента, который они подтверждают.\n"
        "Только русский язык, связный текст без JSON."
    )
