"""Unit tests for EditorChatBridge SSE parsing."""
import json

import pytest

from app.services.editor_chat_bridge import (
    EditorChatBridge,
    _attach_selection_to_edits,
    _parse_sse_data_lines,
)


def test_parse_sse_data_lines():
    chunk = 'data: {"type": "text-delta", "textDelta": "Hello"}\n\n'
    chunk += 'data: {"structured_edits": [{"id": "e1", "new_text": "x", "original_text": "y"}]}\n\n'
    payloads = _parse_sse_data_lines(chunk)
    assert len(payloads) == 2
    assert payloads[0]["textDelta"] == "Hello"
    assert len(payloads[1]["structured_edits"]) == 1


def test_attach_selection_to_edits():
    edits = [{"id": "e1", "new_text": "new", "original_text": "old"}]
    out = _attach_selection_to_edits(
        edits,
        selected_text="old",
        selection_range={"from": 10, "to": 20},
    )
    assert out[0]["selection_range"] == {"from": 10, "to": 20}


def test_route_editor_mode_hints():
    from app.services.langchain_agents.graphs.chat_graph import route_editor_mode

    assert route_editor_mode({"editor_mode_hint": "ask", "question": "x"}) == "generate_response"
    assert route_editor_mode({"editor_mode_hint": "edit", "question": "x"}) == "generate_edits"
    assert route_editor_mode({"editor_mode_hint": "draft", "question": "x"}) == "generate_editor_snippet"


def test_build_document_outline():
    from app.services.langchain_agents.graphs.nodes.editor_nodes import (
        build_document_outline,
        _node_id_in_document,
    )

    html = '<p id="abc-123">Текст абзаца</p><h1 id="h1">Заголовок</h1>'
    outline = build_document_outline(html)
    assert len(outline) == 2
    assert outline[0]["node_id"] == "abc-123"
    assert _node_id_in_document("abc-123", html)


def test_extract_block_text_and_enrich():
    from app.services.langchain_agents.graphs.nodes.editor_nodes import (
        _extract_block_text_by_node_id,
        _enrich_block_edit,
    )

    html = '<p id="blk-1">Договор аренды</p>'
    assert _extract_block_text_by_node_id(html, "blk-1") == "Договор аренды"
    out = _enrich_block_edit(
        node_id="blk-1",
        original_text="",
        new_text="Договор субаренды",
        document_context=html,
    )
    assert out["original_text"] == "Договор аренды"
    assert out["found_in_document"] is True
