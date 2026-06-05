"""Память диалога редактора: transcript в Ask/Edit/Draft."""
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.services.langchain_agents.graphs.editor_transcript import (
    editor_memory_block_for_prompt,
    editor_transcript_for_prompt,
)
from app.services.langchain_agents.graphs.nodes.editor_nodes import (
    _editor_memory_section,
    generate_edits_node,
)


def test_editor_transcript_skips_current_question():
    state = {
        "document_context": "<p id='a'>x</p>",
        "messages": [
            HumanMessage(content="найди ИНН"),
            AIMessage(content="ИНН 7743260611 [1]."),
            HumanMessage(content="вставь его"),
        ],
    }
    hist = editor_transcript_for_prompt(state)
    assert "7743260611" in hist
    assert "вставь его" not in hist
    assert "найди ИНН" in hist


def test_editor_memory_block_includes_instruction():
    state = {
        "document_context": "<p>x</p>",
        "messages": [HumanMessage(content="q"), AIMessage(content="ответ")],
    }
    block = editor_memory_block_for_prompt(state)
    assert "ПАМЯТЬ ДИАЛОГА" in block
    assert "ответ" in block


def test_editor_memory_section_wrapper():
    state = {
        "document_context": "doc",
        "messages": [
            HumanMessage(content="a"),
            AIMessage(content="ИНН 7743260611"),
            HumanMessage(content="вставь"),
        ],
    }
    section = _editor_memory_section(state)
    assert "7743260611" in section


def test_generate_edits_prompt_includes_history():
    state = {
        "document_context": '<p id="n1">[ИНН]</p>',
        "question": "вставь его",
        "editor_mode_hint": "edit",
        "messages": [
            HumanMessage(content="ИНН?"),
            AIMessage(content="ИНН 7743260611."),
            HumanMessage(content="вставь его"),
        ],
    }
    captured = {"user_prompt": ""}

    class FakeEdits:
        edits = []

    def fake_invoke(messages):
        for m in messages:
            c = getattr(m, "content", "") or ""
            if "ЗАПРОС" in c or "OUTLINE" in c:
                captured["user_prompt"] = c
        return FakeEdits()

    with patch(
        "app.services.langchain_agents.graphs.nodes.editor_nodes.create_legal_llm",
    ) as mock_llm:
        mock_llm.return_value.with_structured_output.return_value.invoke.side_effect = (
            fake_invoke
        )
        mock_llm.return_value.with_structured_output.return_value = Mock(
            invoke=fake_invoke
        )
        generate_edits_node(state)

    prompt = captured["user_prompt"]
    assert "7743260611" in prompt
    assert "ИСТОРИЯ ДИАЛОГА" in prompt or "ПАМЯТЬ ДИАЛОГА" in prompt
