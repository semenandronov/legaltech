"""Langfuse helpers for document editor."""
from app.services.observability.editor_langfuse_tracing import (
    build_editor_trace_metadata,
    editor_state_summary,
    enrich_editor_graph_node_metadata,
)


def test_build_editor_trace_metadata_tags():
    meta = build_editor_trace_metadata(
        case_id="c1",
        document_id="d1",
        editor_mode_hint="edit",
        user_id="u1",
    )
    assert meta["feature"] == "document_editor"
    assert meta["mode"] == "edit"
    assert meta["document_id"] == "d1"
    assert "editor_edit" in (meta.get("tags") or [])


def test_enrich_generate_edits_node():
    meta = enrich_editor_graph_node_metadata(
        "generate_edits",
        {"structured_edits": [{"id": "e1"}, {"id": "e2"}]},
        editor_mode_hint="edit",
    )
    assert meta["structured_edits_count"] == 2


def test_editor_state_summary():
    s = editor_state_summary(
        {
            "case_id": "c",
            "document_id": "d",
            "editor_mode_hint": "ask",
            "question": "ИНН?",
            "document_context": "<p>x</p>",
            "messages": [],
        }
    )
    assert s["editor_mode_hint"] == "ask"
    assert s["document_context_chars"] == len("<p>x</p>")
