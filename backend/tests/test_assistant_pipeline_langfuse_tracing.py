from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

import pytest

from app.services.observability import assistant_pipeline_langfuse_tracing as mod


@contextmanager
def _fake_trace_ctx() -> Iterator[object]:
    yield object()


def test_assistant_pipeline_tracing_respects_config(monkeypatch):
    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod.config, "ASSISTANT_PIPELINE_LANGFUSE_DETAILED", False)
    monkeypatch.setattr(mod.config, "CASE_ASSISTANT_LANGFUSE_DETAILED", False)
    assert mod.assistant_pipeline_tracing_enabled() is False

    monkeypatch.setattr(mod.config, "CASE_ASSISTANT_LANGFUSE_DETAILED", True)
    assert mod.assistant_pipeline_tracing_enabled() is True


def test_assistant_step_span_records_latency(monkeypatch):
    events: List[Dict[str, Any]] = []
    ended: List[Dict[str, Any]] = []

    class _Span:
        def update(self, **kwargs: Any) -> None:
            ended.append(kwargs)

        def end(self) -> None:
            pass

    def _fake_span(*_a, **_k):
        return _Span()

    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod.config, "ASSISTANT_PIPELINE_LANGFUSE_DETAILED", True)
    monkeypatch.setattr(mod, "get_active_trace_context", lambda: _fake_trace_ctx())
    monkeypatch.setattr(mod, "trace_span", _fake_span)
    monkeypatch.setattr(
        mod,
        "trace_contract_event",
        lambda _ctx, name, **kwargs: events.append({"name": name, **kwargs}),
    )
    monkeypatch.setattr(mod, "set_trace_span_parent", lambda _span: "token")
    monkeypatch.setattr(mod, "reset_trace_span_parent", lambda _token: None)

    with mod.assistant_step_span("case", "http.test_step", input_payload={"x": 1}) as out:
        out["ok"] = True

    assert any(e["name"] == "step_started" for e in events)
    completed = [e for e in events if e["name"] == "step_completed"]
    assert completed
    assert completed[0]["output_payload"]["ok"] is True
    assert "latency_ms" in completed[0]["output_payload"]
    assert ended


def test_record_execution_branch_emits_event(monkeypatch):
    events: List[Dict[str, Any]] = []

    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod.config, "ASSISTANT_PIPELINE_LANGFUSE_DETAILED", True)
    monkeypatch.setattr(mod, "get_active_trace_context", _fake_trace_ctx)
    monkeypatch.setattr(
        mod,
        "trace_contract_event",
        lambda _ctx, *, name, metadata=None, output_payload=None: events.append(
            {"name": name, "metadata": metadata, "output": output_payload}
        ),
    )

    mod.record_execution_branch("case", branch="langgraph", reason="normal")

    assert len(events) == 1
    assert events[0]["name"] == "execution_branch"
    assert events[0]["output"]["branch"] == "langgraph"


def test_record_graph_node_completed_emits_span_and_event(monkeypatch):
    events: List[Dict[str, Any]] = []
    spans: List[str] = []

    class _Span:
        def update(self, **_k: Any) -> None:
            pass

        def end(self) -> None:
            pass

    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod.config, "ASSISTANT_PIPELINE_LANGFUSE_DETAILED", True)
    monkeypatch.setattr(mod, "get_active_trace_context", _fake_trace_ctx)
    monkeypatch.setattr(
        mod,
        "trace_span",
        lambda *_a, name, **_k: spans.append(name) or _Span(),
    )
    monkeypatch.setattr(
        mod,
        "trace_contract_event",
        lambda _ctx, *, name, metadata=None, output_payload=None: events.append(
            {"name": name, "output": output_payload}
        ),
    )

    mod.record_graph_node_completed(
        "case",
        node_name="generate_response",
        node_data={"response": "ответ", "citations": [{}]},
        since_stream_start_ms=100,
        since_prev_graph_update_ms=50,
    )

    assert spans == ["assistant.case.graph.generate_response"]
    assert events[0]["name"] == "graph_node_completed"
    assert events[0]["output"]["response_chars"] == len("ответ")
    assert events[0]["output"]["citations_count"] == 1


def test_turn_context_trace_fields():
    fields = mod.turn_context_trace_fields(
        {"referential_kind": "memory_synthesis", "needs_document_retrieval": False, "confidence": 0.9}
    )
    assert fields["referential_kind"] == "memory_synthesis"
    assert fields["needs_document_retrieval"] is False


def test_assistant_step_span_noop_without_trace(monkeypatch):
    monkeypatch.setattr(mod, "get_active_trace_context", lambda: None)
    with mod.assistant_step_span("global", "noop") as out:
        out["v"] = 1
    assert out["v"] == 1
