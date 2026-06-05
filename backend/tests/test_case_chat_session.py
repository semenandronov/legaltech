"""Case assistant session identity contract."""
import uuid

from app.services.chat.case_chat_session import (
    case_chat_thread_id,
    is_valid_case_chat_session_id,
    resolve_case_chat_session_id,
)


def test_resolve_uses_client_uuid():
    sid = str(uuid.uuid4())
    resolved, kind = resolve_case_chat_session_id(sid)
    assert resolved == sid
    assert kind == "client_session"


def test_resolve_mints_when_missing():
    resolved, kind = resolve_case_chat_session_id(None)
    assert is_valid_case_chat_session_id(resolved)
    assert kind == "new_session"


def test_resolve_mints_when_invalid():
    resolved, kind = resolve_case_chat_session_id("not-a-uuid")
    assert is_valid_case_chat_session_id(resolved)
    assert kind == "new_session"


def test_editor_session_id_rejected():
    assert not is_valid_case_chat_session_id("editor:user:case:doc")
    resolved, kind = resolve_case_chat_session_id("editor:user:case:doc")
    assert kind == "new_session"


def test_case_chat_thread_id():
    sid = str(uuid.uuid4())
    assert case_chat_thread_id("case-1", sid) == f"case-1_{sid}"
