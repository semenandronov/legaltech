"""Session key helpers for chat_session_context tables."""
from __future__ import annotations


def case_session_key(case_id: str, session_id: str) -> str:
    cid = (case_id or "").strip()
    sid = (session_id or "").strip()
    if not cid or not sid:
        return ""
    return f"{cid}:{sid}"


def global_session_key(session_id: str) -> str:
    return (session_id or "").strip()
