"""Editor chat: stable session identifiers."""
from app.services.chat.editor_session import (
    editor_session_id,
    editor_thread_id,
    is_editor_session_id,
)


def test_is_editor_session_id():
    assert is_editor_session_id("editor:u1:c1:d1")
    assert not is_editor_session_id("a7286f80-7ccb-430b-aaac-38975dabccee")
    assert not is_editor_session_id(None)


def test_editor_session_id_stable():
    a = editor_session_id(user_id="u1", case_id="c1", document_id="d1")
    b = editor_session_id(user_id="u1", case_id="c1", document_id="d1")
    assert a == b
    assert "editor:u1:c1:d1" == a


def test_editor_thread_id():
    sid = editor_session_id(user_id="u1", case_id="c1", document_id="d1")
    assert editor_thread_id("c1", sid) == f"c1_{sid}"
