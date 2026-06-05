"""Тесты кэша количества документов дела и write-through буфера сессии."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.services.chat.case_doc_count_cache import (
    invalidate_case_doc_count_cache,
    resolve_case_doc_count,
)
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.session_turn_buffer import (
    buffer_assistant_turn,
    clear_buffered_turn,
    get_buffered_turns,
    merge_session_turns_with_buffer,
)


def test_resolve_case_doc_count_uses_client_hint_without_db():
    db = MagicMock()
    count = resolve_case_doc_count(db, "case-1", hint=4)
    assert count == 4
    db.query.assert_not_called()


def test_resolve_case_doc_count_cache_hit(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.case_doc_count_cache._cache_enabled",
        lambda: True,
    )
    db = MagicMock()
    with patch(
        "app.services.chat.case_doc_count_cache._load_from_db",
        return_value=7,
    ) as load_db:
        assert resolve_case_doc_count(db, "case-2") == 7
        load_db.assert_called_once()
        load_db.reset_mock()
        assert resolve_case_doc_count(db, "case-2") == 7
        load_db.assert_not_called()


def test_invalidate_case_doc_count_cache_forces_db_reload(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.case_doc_count_cache._cache_enabled",
        lambda: True,
    )
    db = MagicMock()
    with patch(
        "app.services.chat.case_doc_count_cache._load_from_db",
        side_effect=[3, 5],
    ) as load_db:
        assert resolve_case_doc_count(db, "case-3") == 3
        invalidate_case_doc_count_cache("case-3")
        assert resolve_case_doc_count(db, "case-3") == 5
        assert load_db.call_count == 2


def test_buffer_assistant_turn_visible_until_cleared(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.session_turn_buffer.persist_writethrough_buffer_enabled",
        lambda: True,
    )
    buffer_assistant_turn(
        scope="case",
        case_id="case-1",
        session_id="sess-1",
        message_id="msg-1",
        content="Ответ ассистента",
    )
    rows = get_buffered_turns(scope="case", case_id="case-1", session_id="sess-1")
    assert len(rows) == 1
    assert rows[0].content == "Ответ ассистента"
    clear_buffered_turn(
        scope="case",
        case_id="case-1",
        session_id="sess-1",
        message_id="msg-1",
    )
    assert get_buffered_turns(scope="case", case_id="case-1", session_id="sess-1") == []


def test_merge_session_turns_with_buffer_appends_pending_assistant():
    db_turns = [
        SessionMessageTurn(
            message_id="u1",
            role="user",
            content="Вопрос",
            created_at=datetime(2026, 1, 1, 12, 0, 0),
        )
    ]
    from app.services.chat.session_turn_buffer import BufferedSessionTurn

    buffered = [
        BufferedSessionTurn(
            message_id="a1",
            role="assistant",
            content="Ответ",
            created_at=datetime(2026, 1, 1, 12, 0, 5),
        )
    ]
    merged = merge_session_turns_with_buffer(db_turns, buffered)
    assert [t.message_id for t in merged] == ["u1", "a1"]


def test_should_sync_persist_false_when_writethrough_and_async(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.session_context_service.session_context_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence.persist_writethrough_buffer_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence.assistant_async_persist_enabled",
        lambda: True,
    )
    from app.services.chat.assistant_turn_persistence import should_sync_persist_before_finish

    assert should_sync_persist_before_finish() is False
