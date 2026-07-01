"""
Immutable execution contract for one user turn.

Single source: effective_query, information_need, SQL hints — consumed by
router, SQL pipeline, RAG retrieval, and graph state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    InformationNeed,
    load_prior_turn_state,
)
from app.services.chat.turn_context_evidence import PriorTurnEvidence
from app.services.chat.turn_delta_resolver import resolve_turn_delta_if_needed


@dataclass(frozen=True)
class TurnExecutionContract:
    original_question: str
    effective_query: str
    information_need: InformationNeed
    sql_plan_hints: Dict[str, str]
    prior_turn_state: Optional[ConversationTurnState]
    resolver: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        if self.prior_turn_state is not None:
            out["prior_turn_state"] = self.prior_turn_state.to_dict()
        else:
            out["prior_turn_state"] = None
        return out


def _baseline_effective_query(
    question: str,
    turn_context: Optional[Dict[str, Any]],
) -> str:
    q = (question or "").strip()
    if not isinstance(turn_context, dict):
        return q
    standalone = str(turn_context.get("standalone_query") or "").strip()
    if standalone and len(standalone) >= 4:
        return standalone
    return q


def resolve_turn_execution_contract(
    *,
    question: str,
    turn_context: Optional[Dict[str, Any]] = None,
    prior_evidence: Optional[PriorTurnEvidence] = None,
) -> TurnExecutionContract:
    original = (question or "").strip()
    prior_state = load_prior_turn_state(prior_evidence)
    effective = _baseline_effective_query(original, turn_context)
    need: InformationNeed = "unknown"
    hints: Dict[str, str] = {}
    resolver = "baseline"
    reason = "explicit_question"

    delta = resolve_turn_delta_if_needed(
        question=original,
        prior_turn_state=prior_state,
        turn_context=turn_context,
        prior_evidence=prior_evidence,
    )
    if delta is not None:
        effective = delta.effective_query
        need = delta.information_need
        hints = dict(delta.sql_plan_hints)
        resolver = delta.resolver
        reason = delta.reason
    else:
        need = "unknown"

    return TurnExecutionContract(
        original_question=original,
        effective_query=effective,
        information_need=need,
        sql_plan_hints=hints,
        prior_turn_state=prior_state,
        resolver=resolver,
        reason=reason,
    )
