"""Tests for final assistant text extraction."""
from langchain_core.messages import AIMessage, HumanMessage

from app.services.agent_runs.result_extractor import extract_final_assistant_text


def test_extract_last_ai_without_tool_calls():
    messages = [
        HumanMessage(content="Задача"),
        AIMessage(content="", tool_calls=[{"name": "agent_case_search", "args": {}, "id": "1"}]),
        AIMessage(content="## Итог\nСумма 4,5 млн ₽."),
    ]
    assert "4,5 млн" in extract_final_assistant_text(messages)


def test_extract_from_dict_messages():
    messages = [
        {"role": "user", "content": "Анализ"},
        {"role": "assistant", "content": "План готов", "tool_calls": [{"id": "t1"}]},
        {"role": "assistant", "content": "Риски: просрочка оплаты."},
    ]
    assert extract_final_assistant_text(messages) == "Риски: просрочка оплаты."


def test_extract_list_content_blocks():
    messages = [
        AIMessage(content=[{"type": "text", "text": "Таблица реквизитов готова."}]),
    ]
    assert "Таблица" in extract_final_assistant_text(messages)
