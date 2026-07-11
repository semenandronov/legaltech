"""
Load prior assistant turns with server-owned evidence for in-session reference resolution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

from sqlalchemy.orm import Session

from app.services.chat.evidence_bundle import evidence_citations
from app.services.chat.reference_resolver import (
    ReferenceIntent,
    ReferenceKind,
    classify_reference_intent,
    evidence_matches_case_numbers,
    pick_case_number_for_ordinal,
)

logger = logging.getLogger(__name__)

Scope = Literal["case", "global"]
_MAX_CANDIDATES = 40


@dataclass(frozen=True)
class SessionEvidenceReply:
    """Resolved prior assistant answer to stream without re-running retrieval."""

    content: str
    citations: List[dict]
    resolution_kind: str
    message_id: Optional[str] = None
    matched_case_numbers: tuple[str, ...] = ()


def _assistant_rows_case(db: Session, *, case_id: str, session_id: str) -> list[Any]:
    from app.models.case import ChatMessage

    return (
        db.query(ChatMessage)
        .filter(
            ChatMessage.case_id == case_id,
            ChatMessage.session_id == session_id,
            ChatMessage.role == "assistant",
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
            ChatMessage.evidence.isnot(None),
            (~ChatMessage.session_id.like("editor:%")),
            (~ChatMessage.session_id.like("tabular:%")),
            (~ChatMessage.session_id.like("operations:%")),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(_MAX_CANDIDATES)
        .all()
    )


def _assistant_rows_global(db: Session, *, session_id: str) -> list[Any]:
    from app.models.case import GlobalAssistantMessage

    return (
        db.query(GlobalAssistantMessage)
        .filter(
            GlobalAssistantMessage.session_id == session_id,
            GlobalAssistantMessage.role == "assistant",
            GlobalAssistantMessage.content.isnot(None),
            GlobalAssistantMessage.content != "",
            GlobalAssistantMessage.evidence.isnot(None),
        )
        .order_by(GlobalAssistantMessage.created_at.desc())
        .limit(_MAX_CANDIDATES)
        .all()
    )


def _row_to_reply(
    row: Any,
    *,
    resolution_kind: str,
    matched_case_numbers: tuple[str, ...] = (),
) -> SessionEvidenceReply:
    return SessionEvidenceReply(
        content=(row.content or "").strip(),
        citations=evidence_citations(row.evidence),
        resolution_kind=resolution_kind,
        message_id=getattr(row, "id", None),
        matched_case_numbers=matched_case_numbers,
    )


def resolve_session_evidence_reply(
    db: Session,
    *,
    scope: Scope,
    session_id: str,
    question: str,
    case_id: Optional[str] = None,
) -> Optional[SessionEvidenceReply]:
    """
    Find a prior assistant message in this session to satisfy a referential follow-up.

    Returns None when the question is not referential or no matching evidence exists.
    """
    sid = (session_id or "").strip()
    if not sid:
        return None

    intent = classify_reference_intent(question)
    if not intent.should_resolve:
        return None

    if scope == "case":
        if not case_id:
            return None
        rows = _assistant_rows_case(db, case_id=case_id, session_id=sid)
    else:
        rows = _assistant_rows_global(db, session_id=sid)

    if not rows:
        return None

    latest = rows[0]

    if intent.kind is ReferenceKind.EXPLICIT_RECAP:
        return _row_to_reply(latest, resolution_kind="explicit_recap")

    if intent.kind is ReferenceKind.ORDINAL_CASE and intent.ordinal_index is not None:
        target = pick_case_number_for_ordinal(latest.evidence, ordinal_index=intent.ordinal_index)
        if target:
            for row in rows:
                if evidence_matches_case_numbers(
                    row.evidence,
                    targets=[target],
                    content=row.content or "",
                ):
                    return _row_to_reply(
                        row,
                        resolution_kind="ordinal_case",
                        matched_case_numbers=(target,),
                    )
        return _row_to_reply(latest, resolution_kind="ordinal_case_fallback")

    if intent.kind is ReferenceKind.CASE_NUMBER and intent.case_numbers:
        targets = intent.case_numbers
        for row in rows:
            if evidence_matches_case_numbers(
                row.evidence,
                targets=targets,
                content=row.content or "",
            ):
                return _row_to_reply(
                    row,
                    resolution_kind="case_number",
                    matched_case_numbers=targets,
                )
        return None

    if intent.kind is ReferenceKind.DEICTIC:
        return _row_to_reply(latest, resolution_kind="deictic_latest")

    return None


def try_resolve_session_evidence_reply(
    db: Session,
    *,
    scope: Scope,
    session_id: str,
    question: str,
    case_id: Optional[str] = None,
) -> Optional[SessionEvidenceReply]:
    """Best-effort wrapper with logging; safe to call on every turn."""
    try:
        return resolve_session_evidence_reply(
            db,
            scope=scope,
            session_id=session_id,
            question=question,
            case_id=case_id,
        )
    except Exception as exc:
        logger.debug("session evidence resolution failed: %s", exc, exc_info=True)
        return None
