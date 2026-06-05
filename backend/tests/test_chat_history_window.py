"""History window defaults for global assistant and case graph memory."""
from __future__ import annotations

from app.services.chat.global_langgraph_service import (
    _global_history_prompt_limits,
    _global_history_summarize_after_turns,
    _recent_history_text,
)
from app.services.langchain_agents.graphs.chat_graph import (
    _case_graph_memory_limits,
    _editor_graph_memory_limits,
)


def test_global_history_prompt_defaults():
    turns, chars = _global_history_prompt_limits()
    assert turns >= 16
    assert chars >= 6400


def test_global_history_includes_more_turns_than_legacy_eight():
    history = [{"role": "user", "content": f"msg-{i}"} for i in range(20)]
    turns, chars = _global_history_prompt_limits()
    text = _recent_history_text(history, max_turns=turns, max_chars=chars)
    assert "msg-19" in text
    assert "msg-4" in text
    assert "msg-0" not in text


def test_global_summarize_kicks_in_after_twenty_turns():
    assert _global_history_summarize_after_turns() >= 20


def test_case_graph_memory_more_generous_than_editor():
    case = _case_graph_memory_limits()
    editor = _editor_graph_memory_limits()
    assert case["keep_last_n"] > editor["keep_last_n"]
    assert case["summarize_threshold"] > editor["summarize_threshold"]
    assert case["max_tokens"] >= editor["max_tokens"]
