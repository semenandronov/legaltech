"""Tests for canonical dialog transcript service."""
from langchain_core.messages import AIMessage, HumanMessage

from app.services.chat.dialog_transcript_service import (
    build_case_turn_messages,
    build_chat_history,
    reconcile_langchain_messages,
    transcript_to_langchain_messages,
    transcript_turns_from_role_content_pairs,
)


def test_transcript_skips_empty_assistant_placeholders():
    turns = transcript_turns_from_role_content_pairs(
        [
            ("user", "Привет"),
            ("assistant", ""),
            ("assistant", "Ответ"),
        ]
    )
    assert turns == [
        {"role": "user", "content": "Привет"},
        {"role": "assistant", "content": "Ответ"},
    ]


def test_build_case_turn_messages_deduplicates_persisted_user_turn():
    transcript = [
        {"role": "user", "content": "Шаг 1"},
        {"role": "assistant", "content": "Ответ 1"},
        {"role": "user", "content": "Шаг 2"},
    ]
    messages = build_case_turn_messages(transcript, "Шаг 2")
    assert len(messages) == 3
    assert isinstance(messages[-1], HumanMessage)
    assert messages[-1].content == "Шаг 2"


def test_build_case_turn_messages_appends_pending_user_turn():
    transcript = [
        {"role": "user", "content": "Шаг 1"},
        {"role": "assistant", "content": "Ответ 1"},
    ]
    messages = build_case_turn_messages(transcript, "Шаг 2")
    assert len(messages) == 3
    assert messages[-1].content == "Шаг 2"


def test_build_chat_history_deduplicates_global_user_turn():
    transcript = [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "B"},
        {"role": "user", "content": "C"},
    ]
    history = build_chat_history(transcript, "C")
    assert history == transcript


def test_reconcile_prefers_db_transcript_over_checkpoint():
    checkpoint = [
        HumanMessage(content="Только checkpoint"),
    ]
    canonical = [
        HumanMessage(content="Шаг 1"),
        AIMessage(content="Ответ 1"),
        HumanMessage(content="Шаг 2"),
    ]
    merged, replaced = reconcile_langchain_messages(checkpoint, canonical)
    assert replaced is True
    assert len(merged) == 3
    assert merged[0].content == "Шаг 1"


def test_reconcile_no_replace_when_signatures_match():
    canonical = [
        HumanMessage(content="Шаг 1"),
        AIMessage(content="Ответ 1"),
    ]
    merged, replaced = reconcile_langchain_messages(canonical, canonical)
    assert replaced is False
    assert len(merged) == 2


def test_transcript_to_langchain_messages_roles():
    lc = transcript_to_langchain_messages(
        [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"},
        ]
    )
    assert isinstance(lc[0], HumanMessage)
    assert isinstance(lc[1], AIMessage)
