"""Stable editor chat session / LangGraph thread ids (one dialog per document)."""
from __future__ import annotations

import re
import uuid

EDITOR_SESSION_PREFIX = "editor:"


def is_editor_session_id(session_id: str | None) -> bool:
    """True for document-editor chat threads (must not appear in case assistant UI)."""
    return bool(str(session_id or "").strip().startswith(EDITOR_SESSION_PREFIX))


def editor_session_id(
    *,
    user_id: str,
    case_id: str,
    document_id: str,
    chat_thread_id: str | None = None,
) -> str:
    """
    Persistent session key for editor chat history + checkpoints.

    Default: one thread per (user, case, document).
    With chat_thread_id: separate LangGraph checkpoint (новый диалог в UI).
    """
    doc = (document_id or "new").strip()
    base = f"editor:{user_id}:{case_id}:{doc}"
    if not chat_thread_id:
        return base
    tid = str(chat_thread_id).strip()
    if not tid:
        return base
    if tid.startswith(EDITOR_SESSION_PREFIX):
        return tid
    if re.fullmatch(r"[0-9a-fA-F-]{8,64}", tid):
        return f"{base}:{tid}"
    return f"{base}:{tid}"


def editor_session_prefix(*, user_id: str, case_id: str, document_id: str) -> str:
    doc = (document_id or "new").strip()
    return f"editor:{user_id}:{case_id}:{doc}"


def resolve_editor_chat_session_id(
    *,
    user_id: str,
    case_id: str,
    document_id: str,
    requested_session_id: str | None = None,
) -> str:
    """
    Принимает session_id от клиента только если он относится к этому документу/пользователю.
    Иначе — стабильная сессия по документу.
    """
    prefix = editor_session_prefix(
        user_id=user_id,
        case_id=case_id,
        document_id=document_id,
    )
    req = (requested_session_id or "").strip()
    if req and (req == prefix or req.startswith(prefix + ":")):
        return req
    return prefix


def new_editor_chat_session_id(*, user_id: str, case_id: str, document_id: str) -> str:
    """Новый диалог: отдельный checkpoint (UUID-суффикс)."""
    return editor_session_id(
        user_id=user_id,
        case_id=case_id,
        document_id=document_id,
        chat_thread_id=str(uuid.uuid4()),
    )


def editor_thread_id(case_id: str, session_id: str) -> str:
    """LangGraph checkpoint thread_id (same pattern as case assistant)."""
    return f"{case_id}_{session_id}"
