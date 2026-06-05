"""Тесты фоновой персистенции ответов ассистента."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.chat.assistant_turn_persistence import (
    CaseAssistantPersistJob,
    GlobalAssistantPersistJob,
    assistant_async_persist_enabled,
    persist_case_assistant_sync,
    schedule_case_assistant_persist,
    should_sync_persist_before_finish,
)


def test_assistant_async_persist_enabled_default_true():
    assert assistant_async_persist_enabled() is True


def test_should_sync_persist_before_finish_follows_session_context(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.session_context_service.session_context_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence.persist_writethrough_buffer_enabled",
        lambda: False,
    )
    assert should_sync_persist_before_finish() is True
    monkeypatch.setattr(
        "app.services.chat.session_context_service.session_context_enabled",
        lambda: False,
    )
    assert should_sync_persist_before_finish() is False


def test_schedule_case_assistant_persist_creates_task():
    job = CaseAssistantPersistJob(
        message_id="msg-1",
        case_id="case-1",
        session_id="sess-1",
        content="Ответ",
    )
    with patch(
        "app.services.chat.assistant_turn_persistence.assistant_async_persist_enabled",
        return_value=True,
    ), patch(
        "app.services.chat.assistant_turn_persistence.asyncio.create_task"
    ) as create_task:
        schedule_case_assistant_persist(job)
        create_task.assert_called_once()


def test_persist_case_sync_updates_message(monkeypatch):
    db = MagicMock()
    history = MagicMock()
    history.update_assistant_message.return_value = True

    monkeypatch.setattr(
        "app.utils.database.SessionLocal",
        lambda: db,
    )
    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence.ChatHistoryService",
        lambda _db: history,
    )
    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence.refresh_session_context_after_turn",
        lambda *a, **k: None,
    )

    ok = persist_case_assistant_sync(
        CaseAssistantPersistJob(
            message_id="m1",
            case_id="c1",
            session_id="s1",
            content="текст",
            last_user="вопрос",
            last_assistant="текст",
        )
    )
    assert ok is True
    history.update_assistant_message.assert_called_once()
    db.close.assert_called_once()


@pytest.mark.asyncio
async def test_persist_case_retry_succeeds_on_second_attempt(monkeypatch):
    calls = {"n": 0}

    def _sync(job):
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence._persist_case_sync",
        _sync,
    )
    monkeypatch.setattr(
        "app.services.chat.assistant_turn_persistence.config.ASSISTANT_ASYNC_PERSIST_MAX_RETRIES",
        2,
    )

    from app.services.chat.assistant_turn_persistence import _persist_case_with_retry

    job = CaseAssistantPersistJob(
        message_id="m1",
        case_id="c1",
        session_id="s1",
        content="x",
    )
    await _persist_case_with_retry(job)
    assert calls["n"] == 2
