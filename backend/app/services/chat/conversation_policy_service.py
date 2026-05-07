"""
Conversation policy contract for case/global assistants.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

AssistantScope = Literal["global", "case"]
ConversationMode = Literal[
    "research",
    "case_advice",
    "drafting",
    "review",
    "comparison",
    "clarify",
]
RetrievalMode = Literal["matter", "law", "hybrid", "none"]
CaseRouteLabel = Literal["retrieval", "extraction", "legal_qna", "drafting", "mixed", "fallback"]
TaskTypeLabel = Literal[
    "fact_lookup",
    "single_doc_extraction",
    "multi_doc_synthesis",
    "legal_reasoning",
    "contradiction_check",
    "drafting",
    "clarification",
]
TaskFamilyLabel = Literal[
    "entity_fact",
    "single_doc",
    "multi_doc",
    "reasoning",
    "drafting",
    "clarify",
]
DepthTierLabel = Literal["fast", "deep"]
DraftState = Literal["none", "plan_ready", "awaiting_approval", "approved", "generated", "rejected"]


@dataclass
class RunContext:
    session_id: Optional[str]
    user_id: str
    scope: AssistantScope
    mode: ConversationMode
    matter_context: List[Dict[str, Any]]
    draft_state: DraftState
    retrieval_mode: RetrievalMode
    citation_policy: str = "required"
    case_id: Optional[str] = None
    execution_path: str = "default"

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "mode": self.mode,
            "retrieval_mode": self.retrieval_mode,
            "draft_state": self.draft_state,
            "citation_policy": self.citation_policy,
            "case_id": self.case_id,
            "matter_context_count": len(self.matter_context or []),
            "execution_path": self.execution_path,
        }


@dataclass
class InCaseAssistantStateContract:
    """Canonical state contract for in-case chat runtime."""

    case_id: str
    session_id: Optional[str]
    trace_id: Optional[str]
    question: str
    attached_file_ids: List[str]
    legal_research: bool
    draft_mode: bool
    task_type: TaskTypeLabel
    task_family: TaskFamilyLabel
    depth_tier: DepthTierLabel
    route_confidence: float
    route_reason: str
    budget_profile: Dict[str, Any]
    quality_gate_results: Dict[str, str]
    final_answer: str
    citations: List[Dict[str, Any]]
    artifacts: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "question": self.question,
            "attached_file_ids": list(self.attached_file_ids),
            "legal_research": bool(self.legal_research),
            "draft_mode": bool(self.draft_mode),
            "task_type": self.task_type,
            "task_family": self.task_family,
            "depth_tier": self.depth_tier,
            "route_confidence": float(self.route_confidence),
            "route_reason": self.route_reason,
            "budget_profile": dict(self.budget_profile or {}),
            "quality_gate_results": dict(self.quality_gate_results or {}),
            "final_answer": self.final_answer,
            "citations": list(self.citations or []),
            "artifacts": list(self.artifacts or []),
        }


@dataclass(frozen=True)
class ExecutionCapability:
    mode: ConversationMode
    default_path: str
    citations_required: bool
    retrieval_required: bool
    hitl_required: bool
    allowed_scopes: tuple[AssistantScope, ...]


class ConversationPolicyService:
    """Single policy layer used by case and global assistants."""
    CAPABILITY_MATRIX: Dict[ConversationMode, ExecutionCapability] = {
        "research": ExecutionCapability(
            mode="research",
            default_path="retrieval_first",
            citations_required=True,
            retrieval_required=True,
            hitl_required=False,
            allowed_scopes=("global", "case"),
        ),
        "case_advice": ExecutionCapability(
            mode="case_advice",
            default_path="case_orchestrator",
            citations_required=True,
            retrieval_required=True,
            hitl_required=False,
            allowed_scopes=("global", "case"),
        ),
        "drafting": ExecutionCapability(
            mode="drafting",
            default_path="draft_hitl",
            citations_required=False,
            retrieval_required=False,
            hitl_required=True,
            allowed_scopes=("global", "case"),
        ),
        "review": ExecutionCapability(
            mode="review",
            default_path="editor_review",
            citations_required=True,
            retrieval_required=True,
            hitl_required=False,
            allowed_scopes=("global", "case"),
        ),
        "comparison": ExecutionCapability(
            mode="comparison",
            default_path="comparison_retrieval",
            citations_required=True,
            retrieval_required=True,
            hitl_required=False,
            allowed_scopes=("global", "case"),
        ),
        "clarify": ExecutionCapability(
            mode="clarify",
            default_path="clarify_only",
            citations_required=False,
            retrieval_required=False,
            hitl_required=False,
            allowed_scopes=("global", "case"),
        ),
    }

    @staticmethod
    def map_mode(
        *,
        draft_mode: bool = False,
        document_context: Optional[str] = None,
        legal_research: bool = False,
        deep_think: bool = False,
        mode_hint: Optional[str] = None,
    ) -> ConversationMode:
        if mode_hint in {"research", "case_advice", "drafting", "review", "comparison", "clarify"}:
            return mode_hint  # explicit frontend override
        if draft_mode:
            return "drafting"
        if document_context:
            return "review"
        if legal_research:
            return "research"
        if deep_think:
            return "case_advice"
        return "case_advice"

    @staticmethod
    def map_retrieval_mode(
        *,
        scope: AssistantScope,
        mode: ConversationMode,
        legal_research: bool = False,
        has_matter_context: bool = False,
    ) -> RetrievalMode:
        if mode == "clarify":
            return "none"
        if mode == "research":
            return "law" if legal_research else "hybrid"
        if mode in {"review", "comparison", "case_advice"}:
            if has_matter_context and legal_research:
                return "hybrid"
            if has_matter_context:
                return "matter"
            return "law" if legal_research else "none"
        if mode == "drafting":
            if scope == "global":
                return "hybrid" if legal_research else "matter"
            return "matter"
        return "hybrid"

    @staticmethod
    def map_case_route(
        *,
        mode: ConversationMode,
        retrieval_mode: RetrievalMode,
        draft_mode: bool = False,
        deep_think: bool = False,
        legal_research: bool = False,
        attached_files_count: int = 0,
    ) -> tuple[CaseRouteLabel, str, float]:
        # Strict routing contract for internal assistant:
        # DRAFT > СПРАВОЧНИК > default(case-only extraction).
        if draft_mode or mode == "drafting":
            return "drafting", "draft_mode", 0.98
        if legal_research:
            return "mixed", "legal_research_toggle_priority", 0.92
        return "extraction", "default_case_only", 0.90

    @staticmethod
    def infer_task_and_depth(
        *,
        question: str,
        draft_mode: bool = False,
        legal_research: bool = False,
        deep_think: bool = False,
        attached_files_count: int = 0,
    ) -> tuple[TaskTypeLabel, DepthTierLabel, bool, str, float]:
        q = (question or "").strip().lower()
        if not q:
            return "clarification", "fast", True, "empty_question", 0.99
        if draft_mode:
            return "drafting", "deep", False, "draft_mode", 0.98
        if len(q) < 4:
            return "clarification", "fast", True, "too_short_query", 0.93

        fast_fact_markers = (
            "какая сумма",
            "какая дата",
            "кто",
            "какой срок",
            "какой пункт",
            "номер дела",
            "дата",
            "сумма",
            "срок",
        )
        deep_markers = (
            "обзор",
            "о чем все документы",
            "риски",
            "противореч",
            "сравни",
            "проанализируй",
            "правовая позиция",
            "соответствует ли",
            "нарушение",
            "хронолог",
            "таймлайн",
        )
        clarify_markers = (
            "уточни",
            "не понял",
            "что именно",
            "по какому документу",
            "по какому периоду",
            "что сравнить",
            "какому делу",
            "без контекста",
        )
        contradiction_markers = ("противореч", "расхожд", "несоответств")
        synthesis_markers = ("хронолог", "сравни", "сводк", "обзор", "по всем документам", "итог")
        legal_markers = ("закон", "статья", "кодекс", "норма", "правовая позиция", "нарушение")

        if any(m in q for m in clarify_markers):
            return "clarification", "fast", True, "clarification_markers", 0.9

        # Ambiguous short requests should clarify instead of spending deep budget.
        has_question_word = any(x in q for x in ("кто", "что", "какой", "какая", "какие", "где", "когда"))
        has_scope_hint = any(x in q for x in ("документ", "дело", "пункт", "срок", "дата", "сумма"))
        if len(q) <= 24 and has_question_word and not has_scope_hint and attached_files_count == 0:
            return "clarification", "fast", True, "ambiguous_short_query", 0.72

        if any(m in q for m in contradiction_markers):
            return "contradiction_check", "deep", False, "contradiction_markers", 0.9
        if any(m in q for m in synthesis_markers) and attached_files_count > 1:
            return "multi_doc_synthesis", "deep", False, "multi_doc_synthesis_markers", 0.88
        if any(m in q for m in deep_markers):
            return "multi_doc_synthesis", "deep", False, "deep_markers", 0.82
        if legal_research and any(m in q for m in legal_markers):
            return "legal_reasoning", "deep", False, "legal_research_query", 0.85
        if deep_think:
            return "legal_reasoning", "deep", False, "deep_think_enabled", 0.8
        if attached_files_count > 3 and ("все" in q or "обзор" in q):
            return "multi_doc_synthesis", "deep", False, "multi_docs_overview", 0.8
        if any(m in q for m in fast_fact_markers):
            return "fact_lookup", "fast", False, "fast_fact_markers", 0.86
        if attached_files_count <= 1 and len(q) <= 180:
            return "single_doc_extraction", "fast", False, "short_single_doc_query", 0.7
        return "legal_reasoning", "deep", False, "default_deep_path", 0.62

    @staticmethod
    def map_task_family(task_type: TaskTypeLabel) -> TaskFamilyLabel:
        if task_type in {"fact_lookup"}:
            return "entity_fact"
        if task_type in {"single_doc_extraction"}:
            return "single_doc"
        if task_type in {"multi_doc_synthesis", "contradiction_check"}:
            return "multi_doc"
        if task_type in {"legal_reasoning"}:
            return "reasoning"
        if task_type in {"drafting"}:
            return "drafting"
        return "clarify"

    @staticmethod
    def budget_profile_for_depth(
        depth_tier: DepthTierLabel,
        task_type: TaskTypeLabel,
        *,
        corpus_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        if depth_tier == "fast":
            return {
                "name": "fast",
                "max_tool_calls": 2,
                "max_llm_calls": 1,
                # Soft budget hint for fast path (graph may enforce call timeouts separately).
                "max_wall_time_ms": 45_000,
                "max_retries": 1,
                "max_sources": 6,
                "max_context_chars": 3200,
                "max_tokens": 1200,
                # Single-pass k for fast: avoids triple retrieval loops while keeping rerank/top-k quality.
                "k_schedule": [8],
                "max_passes": 1,
            }
        if task_type == "drafting":
            return {
                "name": "drafting_deep",
                "max_tool_calls": 12,
                "max_llm_calls": 8,
                "max_wall_time_ms": 0,
                "max_retries": 2,
                "max_sources": 20,
                "max_context_chars": 12000,
                "max_tokens": 10000,
                "k_schedule": [12, 24, 48],
                "max_passes": 4,
            }
        if task_type == "multi_doc_synthesis":
            size = int(corpus_size or 0)
            if size <= 5:
                return {
                    "name": "deep_small",
                    "size_bucket": "small",
                    "max_tool_calls": 8,
                    "max_llm_calls": 5,
                    "max_wall_time_ms": 0,
                    "max_retries": 2,
                    "max_sources": 10,
                    "max_context_chars": 6500,
                    "max_tokens": 4200,
                    "k_schedule": [8, 16, 30],
                    "max_passes": 3,
                }
            if size <= 30:
                return {
                    "name": "deep_medium",
                    "size_bucket": "medium",
                    "max_tool_calls": 10,
                    "max_llm_calls": 6,
                    "max_wall_time_ms": 0,
                    "max_retries": 2,
                    "max_sources": 16,
                    "max_context_chars": 8200,
                    "max_tokens": 5200,
                    "k_schedule": [12, 24, 48],
                    "max_passes": 4,
                }
            return {
                "name": "deep_large",
                "size_bucket": "large",
                "max_tool_calls": 12,
                "max_llm_calls": 8,
                "max_wall_time_ms": 0,
                "max_retries": 2,
                "max_sources": 22,
                "max_context_chars": 10_500,
                "max_tokens": 6800,
                "k_schedule": [16, 32, 64],
                "max_passes": 5,
            }
        return {
            "name": "deep",
            "max_tool_calls": 8,
            "max_llm_calls": 5,
            "max_wall_time_ms": 0,
            "max_retries": 2,
            "max_sources": 12,
            "max_context_chars": 7000,
            "max_tokens": 4500,
            "k_schedule": [10, 20, 40],
            "max_passes": 4,
        }

    @classmethod
    def build_case_state_contract(
        cls,
        *,
        case_id: str,
        session_id: Optional[str],
        trace_id: Optional[str],
        question: str,
        attached_file_ids: Optional[List[str]],
        legal_research: bool,
        draft_mode: bool,
        task_type: TaskTypeLabel,
        route_confidence: float,
        route_reason: str,
    ) -> InCaseAssistantStateContract:
        task_family = cls.map_task_family(task_type)
        depth_tier: DepthTierLabel = "deep" if task_type in {"multi_doc_synthesis", "legal_reasoning", "contradiction_check", "drafting"} else "fast"
        budget_profile = cls.budget_profile_for_depth(
            depth_tier,
            task_type,
            corpus_size=len(attached_file_ids or []),
        )
        return InCaseAssistantStateContract(
            case_id=case_id,
            session_id=session_id,
            trace_id=trace_id,
            question=question,
            attached_file_ids=list(attached_file_ids or []),
            legal_research=bool(legal_research),
            draft_mode=bool(draft_mode),
            task_type=task_type,
            task_family=task_family,
            depth_tier=depth_tier,
            route_confidence=float(route_confidence),
            route_reason=route_reason,
            budget_profile=budget_profile,
            quality_gate_results={},
            final_answer="",
            citations=[],
            artifacts=[],
        )

    @classmethod
    def get_execution_capability(cls, mode: ConversationMode) -> ExecutionCapability:
        return cls.CAPABILITY_MATRIX[mode]

    @staticmethod
    def map_draft_state(
        *,
        draft_mode: bool,
        draft_approved: bool = False,
        draft_rejected: bool = False,
    ) -> DraftState:
        if not draft_mode:
            return "none"
        if draft_rejected:
            return "rejected"
        if draft_approved:
            return "approved"
        return "awaiting_approval"

    @classmethod
    def build_run_context(
        cls,
        *,
        session_id: Optional[str],
        user_id: str,
        scope: AssistantScope,
        case_id: Optional[str] = None,
        matter_context: Optional[List[Dict[str, Any]]] = None,
        draft_mode: bool = False,
        draft_approved: bool = False,
        draft_rejected: bool = False,
        legal_research: bool = False,
        deep_think: bool = False,
        document_context: Optional[str] = None,
        mode_hint: Optional[str] = None,
    ) -> RunContext:
        mctx = matter_context or []
        mode = cls.map_mode(
            draft_mode=draft_mode,
            document_context=document_context,
            legal_research=legal_research,
            deep_think=deep_think,
            mode_hint=mode_hint,
        )
        retrieval_mode = cls.map_retrieval_mode(
            scope=scope,
            mode=mode,
            legal_research=legal_research,
            has_matter_context=bool(mctx),
        )
        draft_state = cls.map_draft_state(
            draft_mode=draft_mode,
            draft_approved=draft_approved,
            draft_rejected=draft_rejected,
        )
        capability = cls.get_execution_capability(mode)
        citation_policy = "required" if capability.citations_required else "best_effort"
        execution_path = capability.default_path
        if scope == "case" and mode == "case_advice":
            execution_path = "case_orchestrator"
        if scope == "global" and mode == "case_advice":
            execution_path = "global_langgraph_answer"
        return RunContext(
            session_id=session_id,
            user_id=user_id,
            scope=scope,
            mode=mode,
            matter_context=mctx,
            draft_state=draft_state,
            retrieval_mode=retrieval_mode,
            citation_policy=citation_policy,
            case_id=case_id,
            execution_path=execution_path,
        )
