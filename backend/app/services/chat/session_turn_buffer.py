"""In-process write-through buffer for assistant turns pending Postgres commit."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import config
from app.services.chat.session_context_types import SessionMessageTurn

logger = logging.getLogger(__name__)

_guard = threading.Lock()
_buffer: Dict[str, List["BufferedSessionTurn"]] = {}


@dataclass
class BufferedSessionTurn:
    message_id: str
    role: str
    content: str
    evidence: Any = None
    created_at: datetime = field(default_factory=datetime.utcnow)


def persist_writethrough_buffer_enabled() -> bool:
    return bool(getattr(config, "ASSISTANT_PERSIST_WRITETHROUGH_BUFFER_ENABLED", True))


def _buffer_key(*, scope: str, case_id: str, session_id: str) -> str:
    return f"{scope}:{case_id}:{session_id}"


def _max_turns() -> int:
    return max(2, int(getattr(config, "ASSISTANT_PERSIST_WRITETHROUGH_MAX_TURNS", 10) or 10))


def buffer_assistant_turn(
    *,
    scope: str,
    case_id: str,
    session_id: str,
    message_id: str,
    content: str,
    evidence: Any = None,
) -> None:
    if not persist_writethrough_buffer_enabled():
        return
    sid = (session_id or "").strip()
    mid = (message_id or "").strip()
    if not sid or not mid:
        return
    turn = BufferedSessionTurn(
        message_id=mid,
        role="assistant",
        content=(content or "").strip(),
        evidence=evidence,
    )
    key = _buffer_key(scope=scope, case_id=case_id or "", session_id=sid)
    with _guard:
        rows = _buffer.setdefault(key, [])
        rows = [r for r in rows if r.message_id != mid]
        rows.append(turn)
        _buffer[key] = rows[-_max_turns() :]


def clear_buffered_turn(
    *,
    scope: str,
    case_id: str,
    session_id: str,
    message_id: str,
) -> None:
    sid = (session_id or "").strip()
    mid = (message_id or "").strip()
    if not sid or not mid:
        return
    key = _buffer_key(scope=scope, case_id=case_id or "", session_id=sid)
    with _guard:
        rows = _buffer.get(key)
        if not rows:
            return
        filtered = [r for r in rows if r.message_id != mid]
        if filtered:
            _buffer[key] = filtered
        else:
            _buffer.pop(key, None)


def get_buffered_turns(
    *,
    scope: str,
    case_id: str,
    session_id: str,
) -> List[BufferedSessionTurn]:
    if not persist_writethrough_buffer_enabled():
        return []
    sid = (session_id or "").strip()
    if not sid:
        return []
    key = _buffer_key(scope=scope, case_id=case_id or "", session_id=sid)
    with _guard:
        return list(_buffer.get(key) or [])


def merge_session_turns_with_buffer(
    db_turns: List[SessionMessageTurn],
    buffered: List[BufferedSessionTurn],
) -> List[SessionMessageTurn]:
    if not buffered:
        return db_turns
    known_ids = {t.message_id for t in db_turns}
    merged = list(db_turns)
    for row in buffered:
        if row.message_id in known_ids:
            continue
        merged.append(
            SessionMessageTurn(
                message_id=row.message_id,
                role=row.role,
                content=row.content,
                evidence=row.evidence,
                created_at=row.created_at,
            )
        )
    merged.sort(key=lambda t: t.created_at or datetime.min)
    return merged
