"""Тесты телеметрии латентности редактора."""
from app.services.observability.editor_latency_trace import (
    EditorTurnLatency,
    analyze_prompt_payload,
)


def test_analyze_prompt_payload_blocks():
    parts = [
        "=== ДОКУМЕНТ В РЕДАКТОРЕ ===\n<text>",
        "=== ИСТОРИЯ ДИАЛОГА ===\nhist",
    ]
    m = analyze_prompt_payload(
        system_prompt="sys" * 100,
        human_payload="human",
        context_parts=parts,
    )
    assert m["system_chars"] == 300
    assert m["human_chars"] == 5
    assert m["context_total_chars"] == sum(len(p) for p in parts)
    assert len(m["context_blocks"]) == 2


def test_editor_turn_latency_notes_ttft_vs_client():
    lat = EditorTurnLatency()
    lat.set_stage("first_sse_token_to_client", ms=8000)
    lat.merge_llm_metrics({"ttft_ms": 1200, "stream_wall_ms": 24000})
    d = lat.to_dict()
    assert d["llm_ttft_ms"] == 1200
    assert d["first_sse_token_ms"] == 8000
    assert any("TTFT" in n for n in d.get("notes") or [])
