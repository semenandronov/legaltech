"""
Scope-first gate for SQL vs RAG routing.

Production contract:
1. Resolve explicit file scope for the turn (attached → inherited → prior statement).
2. Open the SQL decision branch only when scope intersects SQL-capable files
   (case_file_transactions index populated at ingest).
3. Otherwise route to document RAG without invoking the SQL/RAG LLM router.

Memory / referential classification is handled upstream; this module is data-plane only.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    InformationNeed,
    load_prior_turn_state,
)
from app.services.chat.structured_data_capability import (
    DOCUMENT_INFORMATION_NEEDS,
    TABULAR_INFORMATION_NEEDS,
)
from app.services.chat.structured_data_router import (
    StructuredDataRouterResult,
    StructuredDataResolver,
    route_structured_data_plane,
)
from app.services.chat.turn_context_evidence import PriorTurnEvidence
from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    feature_enabled as transactions_feature_enabled,
)

logger = logging.getLogger(__name__)

TurnScopeSource = Literal[
    "attached",
    "inherited",
    "prior_statement",
    "prior_topic",
    "case_wide",
]


@dataclass(frozen=True)
class TurnFileScope:
    """Resolved file scope for structured-data routing on one turn."""

    file_ids: tuple[str, ...]
    source: TurnScopeSource

    @property
    def is_case_wide(self) -> bool:
        return self.source == "case_wide" or not self.file_ids


def _normalize_ids(ids: Optional[Sequence[str]]) -> tuple[str, ...]:
    if not ids:
        return ()
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids:
        fid = str(raw or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            out.append(fid)
    return tuple(out)


def resolve_turn_file_scope(
    *,
    attached_file_ids: Optional[Sequence[str]] = None,
    turn_context: Optional[dict] = None,
    prior_evidence: Optional[PriorTurnEvidence] = None,
    information_need: InformationNeed | str = "unknown",
) -> TurnFileScope:
    """
    Deterministic file scope before SQL vs RAG routing.

    Priority: attached → turn_context inheritance → prior statement file → case-wide.
    """
    attached = _normalize_ids(attached_file_ids)
    if attached:
        return TurnFileScope(file_ids=attached, source="attached")

    tc = turn_context if isinstance(turn_context, dict) else {}
    inherited = _normalize_ids(tc.get("inherited_file_ids"))
    if inherited:
        return TurnFileScope(file_ids=inherited, source="inherited")

    prior_state = load_prior_turn_state(prior_evidence)
    need = str(information_need or "unknown").strip().lower()

    if prior_state is not None:
        if prior_state.domain == "statement_analytics" and prior_state.statement_file_id:
            if need in TABULAR_INFORMATION_NEEDS or need == "unknown":
                return TurnFileScope(
                    file_ids=(prior_state.statement_file_id,),
                    source="prior_statement",
                )
        topic = _normalize_ids(prior_state.topic_file_ids)
        if topic and prior_state.domain in {"document_rag", "hybrid"}:
            if need in DOCUMENT_INFORMATION_NEEDS or need == "document_drill_down":
                return TurnFileScope(file_ids=topic, source="prior_topic")

    return TurnFileScope(file_ids=(), source="case_wide")


def _rag_only_result(
    *,
    reason: str,
    resolver: StructuredDataResolver,
    rag_file_ids: Optional[Sequence[str]] = None,
    information_need: str = "unknown",
    confidence: float = 1.0,
) -> StructuredDataRouterResult:
    return StructuredDataRouterResult(
        data_plane="rag",
        statement_file_ids=[],
        rag_file_ids=list(rag_file_ids or []),
        confidence=confidence,
        reason=reason,
        resolver=resolver,
        information_need=information_need,
    )


def _sql_capable_file_ids(db: Session, case_id: str) -> tuple[str, ...]:
    if not db or not case_id or not transactions_feature_enabled():
        return ()
    return tuple(CaseFileTransactionService.list_transaction_file_ids(db, case_id))


def route_structured_data_for_turn(
    db: Session,
    *,
    case_id: str,
    question: str,
    turn_scope: TurnFileScope,
    attached_file_ids: Optional[Sequence[str]] = None,
    dialog_history: Optional[str] = None,
    information_need: InformationNeed | str = "unknown",
    resolver_hint: Optional[StructuredDataResolver] = None,
    prior_evidence: Optional[PriorTurnEvidence] = None,
) -> StructuredDataRouterResult:
    """
    Scope-first structured data routing.

    Skips SQL/RAG LLM when scope excludes SQL tables or case-wide narrative need.
    """
    q = (question or "").strip()
    need = str(information_need or "unknown").strip().lower()
    sql_ids = set(_sql_capable_file_ids(db, str(case_id)))

    if not q:
        return _rag_only_result(reason="empty_question", resolver="precondition_skip")

    if not sql_ids:
        return _rag_only_result(
            reason="no_sql_files_in_case",
            resolver="precondition_skip",
            information_need=need,
        )

    scope_ids = set(turn_scope.file_ids)
    hint = resolver_hint or "http_prep"

    # --- Narrow scope: only document files in play → RAG, no SQL LLM ---
    if scope_ids and not (scope_ids & sql_ids):
        rag_ids = list(scope_ids)
        logger.info(
            "[ScopeGate] case=%s rag_only scope_files=%s reason=scope_excludes_sql",
            case_id,
            len(rag_ids),
        )
        return _rag_only_result(
            reason="scope_excludes_sql_tables",
            resolver="scope_gate_rag_only",
            rag_file_ids=rag_ids,
            information_need=need if need in DOCUMENT_INFORMATION_NEEDS else "document_narrative",
        )

    # --- Narrow scope with SQL files → SQL branch on intersection only ---
    if scope_ids and (scope_ids & sql_ids):
        sql_candidates = list(scope_ids & sql_ids)
        rag_hint = list(scope_ids - sql_ids)
        logger.info(
            "[ScopeGate] case=%s sql_branch scoped_sql=%s scoped_rag=%s",
            case_id,
            len(sql_candidates),
            len(rag_hint),
        )
        return route_structured_data_plane(
            db,
            case_id=str(case_id),
            question=q,
            attached_file_ids=attached_file_ids,
            dialog_history=dialog_history,
            resolver_hint=hint,
            information_need=need,
            eligible_sql_file_ids=sql_candidates,
            scope_rag_file_ids=rag_hint or None,
        )

    # --- Case-wide scope ---
    if need in DOCUMENT_INFORMATION_NEEDS:
        logger.info("[ScopeGate] case=%s rag_only reason=case_wide_document_need", case_id)
        return _rag_only_result(
            reason=f"case_wide_{need}",
            resolver="scope_gate_rag_only",
            information_need=need,
        )

    if need in TABULAR_INFORMATION_NEEDS:
        logger.info("[ScopeGate] case=%s sql_branch reason=case_wide_tabular_need", case_id)
        return route_structured_data_plane(
            db,
            case_id=str(case_id),
            question=q,
            attached_file_ids=attached_file_ids,
            dialog_history=dialog_history,
            resolver_hint=hint,
            information_need=need,
            eligible_sql_file_ids=list(sql_ids),
        )

    if need == "comparison":
        return route_structured_data_plane(
            db,
            case_id=str(case_id),
            question=q,
            attached_file_ids=attached_file_ids,
            dialog_history=dialog_history,
            resolver_hint=hint,
            information_need=need,
            eligible_sql_file_ids=list(sql_ids),
        )

    # unknown need, case-wide: invoke SQL/RAG LLM (tabular vs narrative disambiguation)
    return route_structured_data_plane(
        db,
        case_id=str(case_id),
        question=q,
        attached_file_ids=attached_file_ids,
        dialog_history=dialog_history,
        resolver_hint=hint,
        information_need=need,
        eligible_sql_file_ids=list(sql_ids),
    )
