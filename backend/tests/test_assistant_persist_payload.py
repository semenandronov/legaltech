"""Tests for assistant message evidence persistence."""
from app.services.chat.assistant_persist_payload import build_case_assistant_evidence


def test_build_case_assistant_evidence_includes_turn_state():
    evidence = build_case_assistant_evidence(
        citations=[{"source_id": "f1", "quote": "x"}],
        turn_state={
            "domain": "statement_analytics",
            "statement_file_id": "f1",
            "operation": "count",
            "date_from": "01.05.2026",
            "date_to": "31.05.2026",
        },
    )
    meta = evidence.get("retrieval_metadata") or {}
    ts = meta.get("turn_state") or {}
    assert ts.get("domain") == "statement_analytics"
    assert ts.get("operation") == "count"
    assert evidence["citations"][0]["source_id"] == "f1"
