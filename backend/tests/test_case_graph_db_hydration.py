"""Tests for case graph DB transcript hydration."""
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from app.services.chat.dialog_transcript_service import build_case_turn_messages
from app.services.langchain_agents.chat_graph_service import ChatGraphService


class _FakeHistoryService:
    def __init__(self, transcript):
        self._transcript = transcript

    def get_history_for_context(self, case_id, session_id):
        return list(self._transcript)


def test_resolve_case_canonical_messages_from_db(monkeypatch):
    transcript = [
        {"role": "user", "content": "Тема: аренда"},
        {"role": "assistant", "content": "Обсудили срок"},
        {"role": "user", "content": "Сделай черновик"},
    ]
    db = MagicMock()
    service = ChatGraphService(db=db, rag_service=MagicMock(), document_processor=MagicMock())

    monkeypatch.setattr(
        "app.services.chat.history_service.ChatHistoryService",
        lambda _db: _FakeHistoryService(transcript),
    )

    messages = service._resolve_case_canonical_messages(
        "case-1",
        "session-1",
        "Сделай черновик",
        hydrate_from_db=True,
    )
    assert messages is not None
    assert len(messages) == 3
    assert messages[0].content == "Тема: аренда"
    assert messages[-1].content == "Сделай черновик"


def test_resolve_case_canonical_messages_skips_editor_hydration():
    db = MagicMock()
    service = ChatGraphService(db=db, rag_service=MagicMock(), document_processor=MagicMock())
    assert (
        service._resolve_case_canonical_messages(
            "case-1",
            "session-1",
            "Q",
            hydrate_from_db=False,
        )
        is None
    )


def test_apply_canonical_messages_replaces_stale_checkpoint():
    service = ChatGraphService(db=MagicMock(), rag_service=MagicMock(), document_processor=MagicMock())
    canonical = build_case_turn_messages(
        [
            {"role": "user", "content": "Шаг 1"},
            {"role": "assistant", "content": "Ответ"},
            {"role": "user", "content": "Шаг 2"},
        ],
        "Шаг 2",
    )
    state = {"messages": [HumanMessage(content="lost context")]}
    service._apply_canonical_messages(state, canonical)
    assert len(state["messages"]) == 3
    assert isinstance(state["messages"][1], AIMessage)


def test_create_initial_chat_state_prebuilt_messages_no_duplicate():
    from app.services.langchain_agents.graphs.chat_graph import create_initial_chat_state

    prebuilt = [
        HumanMessage(content="Шаг 1"),
        AIMessage(content="Ответ"),
        HumanMessage(content="Шаг 2"),
    ]
    state = create_initial_chat_state(
        case_id="c1",
        user_id="u1",
        question="Шаг 2",
        prebuilt_messages=prebuilt,
    )
    assert len(state["messages"]) == 3
    assert state["messages"][-1].content == "Шаг 2"
