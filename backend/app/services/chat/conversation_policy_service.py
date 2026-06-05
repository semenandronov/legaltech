"""
Conversation policy contract for case/global assistants.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from app.config import config

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
        corpus_size: int = 0,
        dialog_history: str = "",
        conversation_summary: str = "",
        anchor_filenames: Optional[List[str]] = None,
    ) -> tuple[TaskTypeLabel, DepthTierLabel, bool, str, float]:
        from app.services.chat.case_assistant_intent import (
            intent_to_policy_tuple,
            resolve_case_assistant_intent,
        )
        from app.services.chat.standalone_query_resolver import resolve_standalone_query

        resolved = resolve_standalone_query(
            question,
            dialog_history=dialog_history,
            conversation_summary=conversation_summary,
            anchor_filenames=anchor_filenames,
        )
        intent = resolve_case_assistant_intent(
            question=resolved.resolved_question,
            attached_files_count=attached_files_count,
            corpus_size=corpus_size,
            draft_mode=draft_mode,
            legal_research=legal_research,
            deep_think=deep_think,
        )
        return intent_to_policy_tuple(intent)

    @staticmethod
    def resolve_case_intent(
        *,
        question: str,
        draft_mode: bool = False,
        legal_research: bool = False,
        deep_think: bool = False,
        attached_files_count: int = 0,
        corpus_size: int = 0,
    ):
        """Full intent object for budget assembly and observability."""
        from app.services.chat.case_assistant_intent import resolve_case_assistant_intent

        return resolve_case_assistant_intent(
            question=question,
            attached_files_count=attached_files_count,
            corpus_size=corpus_size,
            draft_mode=draft_mode,
            legal_research=legal_research,
            deep_think=deep_think,
        )

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
    def _attach_pipeline_budget(
        profile: Dict[str, Any],
        *,
        question: str = "",
        task_type: str = "legal_reasoning",
        depth_tier: str = "deep",
        clarification_needed: bool = False,
        legal_research: bool = False,
        court_practice: bool = False,
        deep_think: bool = False,
        draft_mode: bool = False,
        structured_execution_tier: Optional[str] = None,
        corpus_size: int = 0,
        attached_files_count: int = 0,
        dialog_history: str = "",
        conversation_summary: str = "",
        anchor_filenames: Optional[List[str]] = None,
        turn_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        from app.services.chat.evidence_plan import apply_evidence_plan, apply_turn_context_overrides
        from app.services.chat.execution_tier import (
            attach_pipeline_budget_for_tier,
            resolve_execution_tier,
        )
        from app.services.chat.standalone_query_resolver import resolve_standalone_query

        tc_kind = (
            str((turn_context or {}).get("referential_kind") or "none").strip().lower()
            if isinstance(turn_context, dict)
            else "none"
        )
        if tc_kind != "none" and isinstance(turn_context, dict):
            routing_question = str(turn_context.get("standalone_query") or question).strip()
            standalone_original = str(turn_context.get("original_question") or question).strip()
            standalone_reason = str(turn_context.get("reason") or "turn_context")
            standalone_changed = routing_question != standalone_original
        else:
            standalone = resolve_standalone_query(
                question,
                dialog_history=dialog_history,
                conversation_summary=conversation_summary,
                anchor_filenames=anchor_filenames,
            )
            routing_question = standalone.resolved_question
            standalone_original = standalone.original_question
            standalone_reason = standalone.reason
            standalone_changed = standalone.changed

        intent = ConversationPolicyService.resolve_case_intent(
            question=routing_question,
            draft_mode=draft_mode,
            legal_research=legal_research,
            deep_think=deep_think,
            attached_files_count=attached_files_count,
            corpus_size=corpus_size,
        )
        tier, tier_reason = resolve_execution_tier(
            question=routing_question,
            task_type=intent.task_type,
            depth_tier=intent.depth_tier,
            clarification_needed=intent.clarification_needed,
            legal_research=legal_research,
            court_practice=court_practice,
            deep_think=deep_think,
            draft_mode=draft_mode,
            structured_tier=structured_execution_tier,
            primary_intent=intent.primary,
        )
        out = attach_pipeline_budget_for_tier(
            profile,
            tier,
            response_shape=intent.response_shape,
            response_shape_reason=intent.reason,
            tier_reason=tier_reason,
            primary_intent=intent.primary,
        )
        out = apply_evidence_plan(out, intent=intent)
        out = apply_turn_context_overrides(out, turn_context)
        out["tier_reason"] = tier_reason
        out["intent_reason"] = intent.reason
        out["original_question"] = standalone_original
        out["resolved_question"] = routing_question
        out["query_resolve_reason"] = standalone_reason
        out["query_resolved"] = standalone_changed
        if isinstance(turn_context, dict):
            out["turn_context"] = turn_context
        return out

    @staticmethod
    def budget_profile_for_depth(
        depth_tier: DepthTierLabel,
        task_type: TaskTypeLabel,
        *,
        corpus_size: Optional[int] = None,
        question: str = "",
        clarification_needed: bool = False,
        legal_research: bool = False,
        court_practice: bool = False,
        deep_think: bool = False,
        draft_mode: bool = False,
        structured_execution_tier: Optional[str] = None,
        attached_files_count: int = 0,
        dialog_history: str = "",
        conversation_summary: str = "",
        anchor_filenames: Optional[List[str]] = None,
        turn_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if depth_tier == "fast" and task_type == "multi_doc_synthesis":
            profile = {
                "name": "fast_multi_doc_overview",
                "max_tool_calls": 4,
                "max_llm_calls": 1,
                "max_wall_time_ms": 45_000,
                "max_retries": 1,
                "max_sources": 8,
                "max_context_chars": 16_000,
                "max_tokens": 1200,
                "k_schedule": [8, 16],
                "max_passes": 2,
            }
        elif depth_tier == "fast" and task_type == "legal_reasoning":
            profile = {
                "name": "fast_legal_reasoning",
                "max_tool_calls": 3,
                "max_llm_calls": 1,
                "max_wall_time_ms": 45_000,
                "max_retries": 1,
                "max_sources": 8,
                "max_context_chars": 16_000,
                "max_tokens": 1500,
                "k_schedule": [8, 16],
                "max_passes": 2,
            }
        elif depth_tier == "fast":
            profile = {
                "name": "fast",
                "max_tool_calls": 2,
                "max_llm_calls": 1,
                "max_wall_time_ms": 45_000,
                "max_retries": 1,
                "max_sources": 6,
                "max_context_chars": 16_000,
                "max_tokens": 1200,
                "k_schedule": [8],
                "max_passes": 1,
            }
        elif task_type == "drafting":
            profile = {
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
        elif task_type == "multi_doc_synthesis":
            size = int(corpus_size or 0)
            if size <= 5:
                profile = {
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
            elif size <= 30:
                profile = {
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
            else:
                profile = {
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
        else:
            profile = {
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
        return ConversationPolicyService._attach_pipeline_budget(
            profile,
            question=question,
            task_type=task_type,
            depth_tier=depth_tier,
            clarification_needed=clarification_needed,
            legal_research=legal_research,
            court_practice=court_practice,
            deep_think=deep_think,
            draft_mode=draft_mode,
            structured_execution_tier=structured_execution_tier,
            corpus_size=int(corpus_size or 0),
            attached_files_count=int(attached_files_count or 0),
            dialog_history=dialog_history,
            conversation_summary=conversation_summary,
            anchor_filenames=anchor_filenames,
            turn_context=turn_context,
        )

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
