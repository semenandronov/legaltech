"""Case assistant chat session identity — client-authoritative contract.

Each chat thread is identified by an explicit session_id from the client.
The server never silently attaches a turn to another session based on case-level
timeouts; that heuristic caused empty UI + stale server history mismatches.
"""
from __future__ import annotations

import re
import uuid

from app.services.chat.editor_session import is_editor_session_id

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def is_valid_case_chat_session_id(session_id: str | None) -> bool:
    sid = (session_id or "").strip()
    if not sid or is_editor_session_id(sid):
        return False
    return bool(_UUID_RE.fullmatch(sid))


def resolve_case_chat_session_id(requested_session_id: str | None) -> tuple[str, str]:
    """
    Resolve session for a case-assistant turn.

    Returns (session_id, resolution_kind):
    - client_session: UUID supplied by the client (continue explicit thread)
    - new_session: minted server-side because client sent nothing/invalid id
    """
    sid = (requested_session_id or "").strip()
    if is_valid_case_chat_session_id(sid):
        return sid, "client_session"
    return str(uuid.uuid4()), "new_session"


def case_chat_thread_id(case_id: str, session_id: str) -> str:
    """LangGraph checkpoint thread_id (one dialog per case session)."""
    return f"{case_id}_{session_id}"
