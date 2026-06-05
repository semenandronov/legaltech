"""Global assistant LangGraph short-term memory (messages + checkpoint)."""
from langchain_core.messages import AIMessage, HumanMessage

from app.services.chat.dialog_transcript_service import (
    build_global_turn_messages,
    reconcile_langchain_messages,
)
from app.services.chat.langgraph_dialog_memory import (
    format_messages_for_prompt,
    messages_to_chat_history,
)


def test_build_global_turn_messages_dedup_user():
    transcript = [
        {"role": "user", "content": "первый вопрос"},
        {"role": "assistant", "content": "первый ответ"},
        {"role": "user", "content": "первый вопрос"},
    ]
    msgs = build_global_turn_messages(transcript, "первый вопрос")
    assert len(msgs) == 3
    assert isinstance(msgs[-1], HumanMessage)


def test_reconcile_prefers_db_transcript():
    checkpoint = [
        HumanMessage(content="старый вопрос"),
        AIMessage(content="старый ответ"),
    ]
    canonical = [
        HumanMessage(content="новый вопрос"),
        AIMessage(content="новый ответ"),
        HumanMessage(content="уточнение"),
    ]
    merged, replaced = reconcile_langchain_messages(checkpoint, canonical)
    assert replaced is True
    assert len(merged) == 3


def test_format_messages_includes_assistant_for_clarify():
    messages = [
        HumanMessage(content="субсидиарка"),
        AIMessage(content="Суд указал презумпцию"),
        HumanMessage(content="что суд сказал?"),
    ]
    text = format_messages_for_prompt(messages, max_turns=8, max_chars=4000)
    assert "презумп" in text.lower()
    assert "что суд сказал" in text.lower()


def test_messages_to_chat_history_roundtrip():
    messages = [
        HumanMessage(content="вопрос"),
        AIMessage(content="ответ"),
    ]
    hist = messages_to_chat_history(messages)
    assert hist == [{"role": "user", "content": "вопрос"}, {"role": "assistant", "content": "ответ"}]
