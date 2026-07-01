"""
Structured per-turn state persisted in assistant evidence.

Enables follow-ups without phrase matching: the next turn inherits scope,
period, and operation from the prior resolved turn.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal, Optional, Sequence

from app.services.chat.turn_context_evidence import PriorTurnEvidence

TurnDomain = Literal["none", "statement_analytics", "document_rag", "hybrid"]
InformationNeed = Literal[
    "tabular_aggregate",
    "tabular_list",
    "tabular_find",
    "document_narrative",
    "document_drill_down",
    "comparison",
    "unknown",
]


@dataclass(frozen=True)
class ConversationTurnState:
    domain: TurnDomain = "none"
    statement_file_id: str = ""
    operation: str = ""
    date_from: str = ""
    date_to: str = ""
    on_date: str = ""
    structured_data_plane: str = ""
    rag_file_ids: tuple[str, ...] = ()
    topic_file_ids: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional[ConversationTurnState]:
        if not isinstance(data, dict):
            return None
        domain_raw = str(data.get("domain") or "none").strip().lower()
        domain: TurnDomain = (
            domain_raw
            if domain_raw in {"none", "statement_analytics", "document_rag", "hybrid"}
            else "none"
        )
        rag_ids = data.get("rag_file_ids") or ()
        topic_ids = data.get("topic_file_ids") or ()
        return cls(
            domain=domain,
            statement_file_id=str(data.get("statement_file_id") or "").strip(),
            operation=str(data.get("operation") or "").strip(),
            date_from=str(data.get("date_from") or "").strip(),
            date_to=str(data.get("date_to") or "").strip(),
            on_date=str(data.get("on_date") or "").strip(),
            structured_data_plane=str(data.get("structured_data_plane") or "").strip(),
            rag_file_ids=tuple(str(x).strip() for x in rag_ids if str(x).strip()),
            topic_file_ids=tuple(str(x).strip() for x in topic_ids if str(x).strip()),
        )

    def has_statement_period(self) -> bool:
        if self.on_date.strip():
            return True
        return bool(self.date_from.strip() and self.date_to.strip())

    def context_line(self) -> str:
        parts: list[str] = []
        if self.statement_file_id:
            parts.append(f"file={self.statement_file_id}")
        if self.operation:
            parts.append(f"op={self.operation}")
        if self.on_date:
            parts.append(f"date={self.on_date}")
        elif self.date_from and self.date_to:
            parts.append(f"period={self.date_from}..{self.date_to}")
        if self.domain != "none":
            parts.append(f"domain={self.domain}")
        return "; ".join(parts)


def load_prior_turn_state(prior: PriorTurnEvidence | None) -> Optional[ConversationTurnState]:
    if prior is None:
        return None
    meta = prior.retrieval_metadata if isinstance(prior.retrieval_metadata, dict) else {}
    state = ConversationTurnState.from_dict(meta.get("turn_state"))
    if state is not None and state.domain != "none":
        return state
    legacy_sql = meta.get("statement_sql")
    if isinstance(legacy_sql, dict):
        return ConversationTurnState.from_dict(
            {
                "domain": "statement_analytics",
                "statement_file_id": legacy_sql.get("file_id") or "",
                "operation": legacy_sql.get("operation") or "",
                "date_from": legacy_sql.get("date_from") or "",
                "date_to": legacy_sql.get("date_to") or "",
                "on_date": legacy_sql.get("on_date") or "",
                "structured_data_plane": "sql",
            }
        )
    return None


def turn_state_from_sql_plan(
    *,
    plan: Any,
    file_id: str,
    plane: str = "sql",
) -> ConversationTurnState:
    return ConversationTurnState(
        domain="statement_analytics",
        statement_file_id=str(file_id or getattr(plan, "statement_file_id", "") or "").strip(),
        operation=str(getattr(plan, "operation", "") or "").strip(),
        date_from=str(getattr(plan, "date_from", "") or "").strip(),
        date_to=str(getattr(plan, "date_to", "") or "").strip(),
        on_date=str(getattr(plan, "on_date", "") or "").strip(),
        structured_data_plane=plane,
        topic_file_ids=(str(file_id).strip(),) if file_id else (),
    )


def turn_state_from_rag_scope(
    *,
    file_ids: Sequence[str],
    plane: str = "rag",
) -> ConversationTurnState:
    ids = tuple(str(x).strip() for x in file_ids if str(x).strip())
    return ConversationTurnState(
        domain="document_rag",
        structured_data_plane=plane,
        rag_file_ids=ids,
        topic_file_ids=ids,
    )


def merge_sql_plan_hints(
    prior: Optional[ConversationTurnState],
    *,
    operation_override: str = "",
    inherit_period: bool = True,
    inherit_file: bool = True,
) -> Dict[str, str]:
    """Deterministic hints for SQL planner — no natural-language patterns."""
    hints: Dict[str, str] = {}
    if prior is None or prior.domain != "statement_analytics":
        return hints
    if inherit_file and prior.statement_file_id:
        hints["statement_file_id"] = prior.statement_file_id
    if operation_override:
        hints["operation"] = operation_override
    elif prior.operation:
        hints["operation"] = prior.operation
    if inherit_period:
        if prior.on_date:
            hints["on_date"] = prior.on_date
        if prior.date_from:
            hints["date_from"] = prior.date_from
        if prior.date_to:
            hints["date_to"] = prior.date_to
    return hints
