"""Outbound turn state derivation from graph state."""
from app.services.chat.conversation_turn_state import turn_state_from_rag_scope
from app.services.chat.outbound_turn_state import (
    attach_outbound_turn_state,
    build_outbound_turn_state,
    turn_state_from_hybrid_scope,
)


def test_build_outbound_from_rag_citations():
    state = {
        "structured_data_plane": "rag",
        "citations": [{"source_id": "doc-a"}, {"file_id": "doc-b"}],
    }
    built = build_outbound_turn_state(state)
    assert built is not None
    assert built["domain"] == "document_rag"
    assert "doc-a" in built.get("topic_file_ids", []) or built.get("rag_file_ids")


def test_attach_preserves_sql_outbound():
    existing = {
        "domain": "statement_analytics",
        "operation": "count",
        "statement_file_id": "f1",
    }
    state = {
        "outbound_turn_state": existing,
        "citations": [{"source_id": "other"}],
    }
    out = attach_outbound_turn_state(dict(state))
    assert out["outbound_turn_state"]["operation"] == "count"


def test_hybrid_turn_state_scope():
    ts = turn_state_from_hybrid_scope(
        statement_file_ids=["sql-1"],
        rag_file_ids=["rag-1"],
        sql_operation="sum",
    )
    assert ts.domain == "hybrid"
    assert ts.statement_file_id == "sql-1"
    assert "rag-1" in ts.rag_file_ids


def test_rag_scope_helper():
    ts = turn_state_from_rag_scope(file_ids=["x"], plane="rag")
    assert ts.domain == "document_rag"
    assert ts.topic_file_ids == ("x",)


def test_rag_plane_wins_over_stale_sql_meta_in_checkpoint():
    """After SQL turns, checkpoint may still carry statement_sql_meta; RAG turn must not inherit it."""
    state = {
        "structured_data_plane": "rag",
        "statement_sql_meta": {
            "operation": "count",
            "file_id": "stmt-1",
            "date_from": "01.05.2026",
            "date_to": "31.05.2026",
        },
        "citations": [{"source_id": "objection-doc"}],
    }
    built = build_outbound_turn_state(state)
    assert built is not None
    assert built["domain"] == "document_rag"
    assert "objection-doc" in (built.get("rag_file_ids") or ())
