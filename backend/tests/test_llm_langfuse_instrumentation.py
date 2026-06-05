"""Tests for Langfuse LLM generation instrumentation."""

from __future__ import annotations

from app.services.observability.langfuse_service import (
    TraceContext,
    set_active_trace_context,
    reset_active_trace_context,
)
from app.services.observability import llm_langfuse_instrumentation as mod


class _FakeGeneration:
    def __init__(self) -> None:
        self.ended = False
        self.updated = []

    def update(self, **kwargs):
        self.updated.append(kwargs)
        return self

    def end(self):
        self.ended = True


class _FakeParent:
    def __init__(self, obs_id: str = "parent1234567890ab") -> None:
        self.id = obs_id

    def start_observation(self, **kwargs):
        gen = _FakeGeneration()
        gen.start_kwargs = kwargs
        return gen


class _FakeLLM:
    def __init__(self) -> None:
        self.last_config = None

    def invoke(self, messages, config=None, **kwargs):
        self.last_config = config
        return type("Resp", (), {"content": "ok"})()


def test_get_langchain_callbacks_passes_trace_context(monkeypatch):
    fake_root = _FakeParent("rootspanid123456")
    ctx = TraceContext(
        trace_id="f" * 32,
        started_at=0.0,
        name="assistant_chat_v2",
        metadata={},
        root_observation=fake_root,
        user_id="user-1",
        session_id="sess-1",
    )
    captured = {}

    class _Handler:
        def __init__(self, *, trace_context=None):
            captured["trace_context"] = trace_context

    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod, "LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE", True)
    monkeypatch.setattr(
        "app.services.observability.langfuse_service.LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE",
        True,
    )
    monkeypatch.setattr(
        "app.services.observability.langfuse_service.LangfuseLangchainCallbackHandler",
        _Handler,
    )
    monkeypatch.setattr(
        "app.services.observability.langfuse_service.get_active_trace_context",
        lambda: ctx,
    )

    from app.services.observability.langfuse_service import get_langchain_callbacks

    handlers = get_langchain_callbacks(tags=["assistant"])
    assert len(handlers) == 1
    assert captured["trace_context"]["trace_id"] == "f" * 32
    assert captured["trace_context"]["parent_span_id"] == "rootspanid123456"


def test_langfuse_llm_wrapper_injects_callbacks(monkeypatch):
    fake_handler = object()

    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod, "LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE", True)
    monkeypatch.setattr(mod, "get_langchain_callbacks", lambda **_: [fake_handler])

    llm = _FakeLLM()
    wrapped = mod.LangfuseInstrumentedLLMWrapper(llm)
    wrapped.invoke(["hello"])

    assert llm.last_config is not None
    assert fake_handler in llm.last_config["callbacks"]


def test_observe_generation_creates_and_ends_span(monkeypatch):
    fake_root = _FakeParent()
    ctx = TraceContext(
        trace_id="g" * 32,
        started_at=0.0,
        name="assistant_chat_v2",
        metadata={},
        root_observation=fake_root,
    )
    token = set_active_trace_context(ctx)
    events = []
    monkeypatch.setattr(mod, "langfuse_enabled", lambda: True)
    monkeypatch.setattr(mod, "trace_contract_event", lambda *a, **k: events.append(k.get("name")))
    gen = None
    try:
        with mod.observe_generation("test_generation", model="gpt-test") as active_gen:
            gen = active_gen
            assert gen is not None
        assert gen.ended is True
        assert "llm_generation" in events
    finally:
        reset_active_trace_context(token)
