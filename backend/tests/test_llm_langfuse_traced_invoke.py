from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.services.observability import llm_langfuse_instrumentation as mod


class _FakeLLM:
    model_name = "test-model"

    def invoke(self, messages: List[Any]) -> Any:
        return type("Resp", (), {"content": "hello", "response_metadata": {}})()


def test_traced_sync_llm_invoke_records_metrics(monkeypatch):
    events: List[Dict[str, Any]] = []
    generations: List[str] = []

    class _Gen:
        def update(self, **kwargs: Any) -> None:
            generations.append(str(kwargs.get("output")))

        def end(self) -> None:
            pass

    class _Base:
        def start_observation(self, *args: Any, **kwargs: Any) -> _Gen:
            return _Gen()

    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod, "get_active_trace_context", lambda: object())
    monkeypatch.setattr(mod, "_trace_span_base_observation", lambda _ctx: _Base())
    monkeypatch.setattr(
        mod,
        "trace_contract_event",
        lambda _ctx, name, **kwargs: events.append({"name": name}),
    )

    metrics: Dict[str, Any] = {}
    resp = mod.traced_sync_llm_invoke(
        _FakeLLM(),
        [{"role": "user", "content": "hi"}],
        generation_name="test_gen",
        assistant_step="test.llm_invoke",
        metrics_out=metrics,
    )
    assert hasattr(resp, "content")
    assert metrics.get("invoke_wall_ms") is not None
    assert metrics.get("output_chars") == 5


def test_traced_sync_llm_invoke_noop_without_langfuse(monkeypatch):
    monkeypatch.setattr(mod, "langfuse_enabled", lambda: False)
    resp = mod.traced_sync_llm_invoke(
        _FakeLLM(),
        [],
        generation_name="noop",
    )
    assert resp.content == "hello"
