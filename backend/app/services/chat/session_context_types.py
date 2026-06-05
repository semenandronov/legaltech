"""Shared types for in-session context (one chat thread)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

Scope = Literal["case", "global"]


class TurnRelation(str, Enum):
    NEW_TOPIC = "new_topic"
    FOLLOW_UP = "follow_up"
    CLARIFY_PRIOR = "clarify_prior"


@dataclass(frozen=True)
class SessionMessageTurn:
    message_id: str
    role: str
    content: str
    evidence: Any = None
    created_at: Optional[Any] = None


@dataclass
class SessionResolveResult:
    """LLM session router: dialog relation + memory vs document retrieval."""

    turn_relation: TurnRelation = TurnRelation.FOLLOW_UP
    needs_document_retrieval: bool = True
    focus: str = ""
    anchor_message_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    rationale: str = ""

    @property
    def prefers_memory_only(self) -> bool:
        """Answer from in-chat transcript without a fresh document/corpus search."""
        return not self.needs_document_retrieval

    @property
    def should_replay_prior_answer(self) -> bool:
        """Replay only for clarify_prior when chat memory suffices (no fresh retrieval)."""
        return (
            self.turn_relation is TurnRelation.CLARIFY_PRIOR
            and not self.needs_document_retrieval
        )

    @property
    def prefers_evidence_replay(self) -> bool:
        return self.should_replay_prior_answer


@dataclass
class RelevantTurn:
    message_id: str
    role: str
    content: str
    score: float = 0.0
    source: str = "semantic"


@dataclass
class SessionContextPackage:
    """Always-on session context assembled before each LLM turn."""

    scope: Scope
    session_key: str
    prompt_block: str
    thread_state: Dict[str, Any]
    conversation_summary: str
    resolver: SessionResolveResult
    retrieval_query: str = ""
    relevant_turns: List[RelevantTurn] = field(default_factory=list)
    evidence_replay: Optional[Any] = None  # SessionEvidenceReply when short-circuit
    prior_answer_available: bool = False
    prior_answer_message_id: str = ""
    prior_answer_excerpt: str = ""

    @property
    def should_short_circuit(self) -> bool:
        return self.evidence_replay is not None
