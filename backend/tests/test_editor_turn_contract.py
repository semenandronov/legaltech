"""Tests for editor turn contract and SSE emitter."""
from app.services.chat.turn_contract import (
    normalize_editor_intent,
    reset_editor_ephemeral_for_turn,
    should_emit_patch_proposals,
)
from app.services.chat.turn_emitter import EditorTurnEmitter


def test_normalize_editor_intent_defaults_to_ask():
    assert normalize_editor_intent(None) == "ask"
    assert normalize_editor_intent("EDIT") == "edit"


def test_reset_editor_ephemeral_clears_patch_state():
    state = {
        "structured_edits": [{"id": "e1", "new_text": "x"}],
        "waiting_for_edits_approval": True,
        "response": "old answer",
        "rag_context": "ctx",
    }
    reset_editor_ephemeral_for_turn(state, turn_id="t-1", intent="ask")
    assert state["active_turn_id"] == "t-1"
    assert state["turn_intent"] == "ask"
    assert state["structured_edits"] is None
    assert state["waiting_for_edits_approval"] is False
    assert state["response"] is None
    assert state["rag_context"] is None


def test_should_emit_patch_proposals_only_for_edit_and_producer_nodes():
    assert should_emit_patch_proposals(
        intent="ask",
        graph_node="generate_edits",
        structured_edits=[{"id": "e1"}],
    ) is False
    assert should_emit_patch_proposals(
        intent="edit",
        graph_node="manage_memory",
        structured_edits=[{"id": "e1"}],
    ) is False
    assert should_emit_patch_proposals(
        intent="edit",
        graph_node="generate_edits",
        structured_edits=[{"id": "e1", "new_text": "a"}],
    ) is True


def test_turn_emitter_ask_does_not_use_custom_stream():
    em = EditorTurnEmitter.for_editor("tid", "ask", "doc-1")
    assert em.use_custom_stream_channel() is False
    assert em.structured_edits_from_node("generate_edits", [{"id": "e1"}]) is None


def test_turn_emitter_edit_emits_patches_with_turn_id():
    em = EditorTurnEmitter.for_editor("tid", "edit", "doc-1")
    raw = em.structured_edits_from_node(
        "generate_edits",
        [{"id": "e1", "new_text": "ИНН 7743260611", "found_in_document": True}],
    )
    assert raw is not None
    assert "turn_id" in raw
    assert em.last_patch_count == 1
