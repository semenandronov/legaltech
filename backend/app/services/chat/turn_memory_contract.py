"""
Unified turn memory contract — single decision point per user turn.

Layers (no overlap in routing authority):
- Episodic: prior assistant turn + citations (PriorTurnEvidence)
- Working: ConversationTurnState (period, file scope, domain)
- Document plane: structured SQL / scoped RAG / full case (downstream scope gate)

``execution_mode`` is the only routing switch for memory vs retrieval.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional, Sequence

from app.services.chat.conversation_turn_state import InformationNeed
from app.services.chat.referential_classifier import ReferentialKind
from app.services.chat.session_context_types import SessionMessageTurn, TurnRelation
from app.services.chat.session_replay_policy import is_repeated_user_question
from app.services.chat.structured_data_capability import (
    DOCUMENT_INFORMATION_NEEDS,
    TABULAR_INFORMATION_NEEDS,
)
from app.services.chat.turn_context_evidence import (
    PriorTurnEvidence,
    load_prior_turn_evidence_from_turns,
)
from app.services.chat.turn_context_resolution import (
    TurnContextResolution,
    resolve_turn_context,
    session_result_from_turn_context,
)
from app.services.chat.turn_execution_contract import (
    TurnExecutionContract,
    resolve_turn_execution_contract,
)

ExecutionMode = Literal[
    "chat_replay",
    "scoped_document",
    "structured_sql",
    "hybrid",
    "full_case",
]


@dataclass(frozen=True)
class TurnMemoryContract:
    """Immutable memory + execution routing contract for one user turn."""

    execution_mode: ExecutionMode
    original_question: str
    effective_query: str
    information_need: InformationNeed
    turn_context: TurnContextResolution
    execution_contract: TurnExecutionContract
    prior_evidence: Optional[PriorTurnEvidence]
    resolver: str
    reason: str
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_mode": self.execution_mode,
            "original_question": self.original_question,
            "effective_query": self.effective_query,
            "information_need": self.information_need,
            "turn_context": self.turn_context.to_dict(),
            "execution_contract": self.execution_contract.to_dict(),
            "resolver": self.resolver,
            "reason": self.reason,
            "confidence": self.confidence,
            "referential_kind": self.turn_context.referential_kind,
            "needs_document_retrieval": self.turn_context.needs_document_retrieval,
        }

    @property
    def turn_context_dict(self) -> Dict[str, Any]:
        return self.turn_context.to_dict()

    @property
    def execution_contract_dict(self) -> Dict[str, Any]:
        return self.execution_contract.to_dict()

    def session_resolver_hints(self) -> tuple[TurnRelation, bool]:
        """Map contract to session resolver fields (no second LLM)."""
        result = session_result_from_turn_context(
            self.turn_context,
            prior_evidence=self.prior_evidence,
        )
        return result.turn_relation, result.needs_document_retrieval


def _execution_mode_from_parts(
    *,
    referential_kind: ReferentialKind,
    needs_document_retrieval: bool,
    information_need: InformationNeed,
) -> ExecutionMode:
    if referential_kind == "memory_synthesis" or not needs_document_retrieval:
        return "chat_replay"
    if referential_kind in {"scoped_deep_read", "citation_expand"}:
        return "scoped_document"
    need = str(information_need or "unknown").strip().lower()
    if need in TABULAR_INFORMATION_NEEDS:
        return "structured_sql"
    return "full_case"


def resolve_turn_memory_contract(
    *,
    question: str,
    turns: Sequence[SessionMessageTurn] = (),
    dialog_history: str = "",
    conversation_summary: str = "",
    anchor_filenames: Sequence[str] = (),
    allow_llm_judge: bool = True,
) -> TurnMemoryContract:
    """
    Assemble the single turn memory contract (prep-time, before graph).

    Pipeline:
    1. Load prior episodic evidence
    2. Repeated question → fresh full_case (not replay)
    3. Referential routing (deterministic-first via resolve_turn_context)
    4. Working-memory delta (execution contract)
    5. Map to execution_mode

    FAST latency path sets ``allow_llm_judge=False``.
    """
    original = (question or "").strip()
    prior = load_prior_turn_evidence_from_turns(turns)

    if turns and is_repeated_user_question(original, turns):
        turn_context = TurnContextResolution(
            original_question=original,
            standalone_query=original,
            referential_kind="none",
            inherited_file_ids=(),
            anchor_chunk_ids=(),
            suggested_intent=None,
            needs_document_retrieval=True,
            prefer_parent_context=False,
            reason="repeated_user_question",
            confidence=0.95,
            query_resolver="unchanged",
            routing_resolver="deterministic",
        )
        exec_contract = resolve_turn_execution_contract(
            question=original,
            turn_context=turn_context.to_dict(),
            prior_evidence=prior,
        )
        return TurnMemoryContract(
            execution_mode="full_case",
            original_question=original,
            effective_query=exec_contract.effective_query,
            information_need=exec_contract.information_need,
            turn_context=turn_context,
            execution_contract=exec_contract,
            prior_evidence=prior,
            resolver="deterministic",
            reason="repeated_user_question",
            confidence=0.95,
        )

    turn_context = resolve_turn_context(
        question=original,
        prior_evidence=prior,
        turns=turns,
        dialog_history=dialog_history,
        conversation_summary=conversation_summary,
        anchor_filenames=anchor_filenames,
        allow_llm_judge=allow_llm_judge,
    )
    exec_contract = resolve_turn_execution_contract(
        question=original,
        turn_context=turn_context.to_dict(),
        prior_evidence=prior,
    )

    mode = _execution_mode_from_parts(
        referential_kind=turn_context.referential_kind,
        needs_document_retrieval=turn_context.needs_document_retrieval,
        information_need=exec_contract.information_need,
    )

    resolver = turn_context.routing_resolver or "unchanged"
    reason = turn_context.reason or "turn_memory_contract"

    return TurnMemoryContract(
        execution_mode=mode,
        original_question=original,
        effective_query=exec_contract.effective_query,
        information_need=exec_contract.information_need,
        turn_context=turn_context,
        execution_contract=exec_contract,
        prior_evidence=prior,
        resolver=resolver,
        reason=reason,
        confidence=turn_context.confidence,
    )


def apply_structured_plane_to_contract(
    contract: TurnMemoryContract,
    *,
    data_plane: str,
) -> TurnMemoryContract:
    """
    Refine execution_mode after scope gate (sql / rag / hybrid).

    chat_replay and scoped_document are not changed here.
    """
    plane = (data_plane or "").strip().lower()
    if contract.execution_mode in {"chat_replay", "scoped_document"}:
        return contract
    if plane == "hybrid":
        return TurnMemoryContract(
            execution_mode="hybrid",
            original_question=contract.original_question,
            effective_query=contract.effective_query,
            information_need=contract.information_need,
            turn_context=contract.turn_context,
            execution_contract=contract.execution_contract,
            prior_evidence=contract.prior_evidence,
            resolver=contract.resolver,
            reason=f"{contract.reason};plane_hybrid",
            confidence=contract.confidence,
        )
    if plane == "sql":
        return TurnMemoryContract(
            execution_mode="structured_sql",
            original_question=contract.original_question,
            effective_query=contract.effective_query,
            information_need=contract.information_need,
            turn_context=contract.turn_context,
            execution_contract=contract.execution_contract,
            prior_evidence=contract.prior_evidence,
            resolver=contract.resolver,
            reason=f"{contract.reason};plane_sql",
            confidence=contract.confidence,
        )
    if plane == "rag" and contract.execution_mode == "structured_sql":
        need = str(contract.information_need or "").strip().lower()
        if need in DOCUMENT_INFORMATION_NEEDS:
            return TurnMemoryContract(
                execution_mode="scoped_document"
                if contract.turn_context.referential_kind in {"scoped_deep_read", "citation_expand"}
                else "full_case",
                original_question=contract.original_question,
                effective_query=contract.effective_query,
                information_need=contract.information_need,
                turn_context=contract.turn_context,
                execution_contract=contract.execution_contract,
                prior_evidence=contract.prior_evidence,
                resolver=contract.resolver,
                reason=f"{contract.reason};plane_rag_override",
                confidence=contract.confidence,
            )
    return contract


def memory_contract_skips_structured_router(contract: TurnMemoryContract) -> bool:
    """True when scope gate / SQL router must not run."""
    return contract.execution_mode == "chat_replay"


def memory_contract_forces_scoped_rag(contract: TurnMemoryContract) -> bool:
    return contract.execution_mode == "scoped_document"
