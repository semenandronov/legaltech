"""Load session messages with ids for context assembly."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from app.services.chat.editor_session import is_editor_session_id
from app.services.chat.session_context_types import SessionMessageTurn


def load_case_session_turns(
    db: Session,
    *,
    case_id: str,
    session_id: str,
    limit: int = 80,
) -> List[SessionMessageTurn]:
    from app.models.case import ChatMessage

    sid = (session_id or "").strip()
    cid = (case_id or "").strip()
    if not sid or not cid or is_editor_session_id(sid):
        return []

    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.case_id == cid,
            ChatMessage.session_id == sid,
            ChatMessage.content.isnot(None),
            ChatMessage.content != "",
        )
        .order_by(ChatMessage.created_at.asc())
        .limit(max(1, limit))
        .all()
    )
    db_turns = [
        SessionMessageTurn(
            message_id=str(r.id),
            role=str(r.role or ""),
            content=(r.content or "").strip(),
            evidence=r.evidence,
            created_at=r.created_at,
        )
        for r in rows
    ]
    from app.services.chat.session_turn_buffer import (
        get_buffered_turns,
        merge_session_turns_with_buffer,
    )

    buffered = get_buffered_turns(scope="case", case_id=cid, session_id=sid)
    return merge_session_turns_with_buffer(db_turns, buffered)


def load_global_session_turns(
    db: Session,
    *,
    session_id: str,
    limit: int = 80,
) -> List[SessionMessageTurn]:
    from app.models.case import GlobalAssistantMessage

    sid = (session_id or "").strip()
    if not sid:
        return []

    rows = (
        db.query(GlobalAssistantMessage)
        .filter(
            GlobalAssistantMessage.session_id == sid,
            GlobalAssistantMessage.content.isnot(None),
            GlobalAssistantMessage.content != "",
        )
        .order_by(GlobalAssistantMessage.created_at.asc())
        .limit(max(1, limit))
        .all()
    )
    return [
        SessionMessageTurn(
            message_id=str(r.id),
            role=str(r.role or ""),
            content=(r.content or "").strip(),
            evidence=r.evidence,
            created_at=r.created_at,
        )
        for r in rows
    ]


def turns_to_resolver_transcript(
    turns: List[SessionMessageTurn],
    *,
    max_turns: int = 12,
    max_chars_per_turn: int = 1200,
) -> str:
    """Compact transcript for LLM resolver."""
    if not turns:
        return ""
    tail = turns[-max_turns:]
    lines: List[str] = []
    for t in tail:
        role = "user" if (t.role or "").lower() == "user" else "assistant"
        content = (t.content or "")[:max_chars_per_turn]
        lines.append(f"[{t.message_id}] {role}: {content}")
    return "\n".join(lines)
