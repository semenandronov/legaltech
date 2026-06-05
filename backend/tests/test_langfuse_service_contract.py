from app.services.observability.langfuse_service import (
    TraceContext,
    create_trace_context,
    end_trace,
    trace_event,
    update_trace,
    start_trace_attribute_scope,
    set_active_trace_context,
    get_active_trace_context,
)


class _FakeEvent:
    def __init__(self) -> None:
        self.ended = False

    def end(self) -> None:
        self.ended = True


class _FakeRootObservation:
    def __init__(self) -> None:
        self.created_events = []
        self.updated_payloads = []
        self.last_event = None

    def create_event(self, **kwargs):
        self.created_events.append(kwargs)
        self.last_event = _FakeEvent()
        return self.last_event

    def update(self, **kwargs):
        self.updated_payloads.append(kwargs)
        return self


def test_trace_event_prefers_root_observation_create_event():
    fake_root = _FakeRootObservation()
    ctx = TraceContext(
        trace_id="a" * 32,
        started_at=0.0,
        name="assistant_chat_v2",
        metadata={},
        root_observation=fake_root,
    )

    trace_event(
        ctx,
        name="request_received",
        metadata={"assistant_type": "case_assistant"},
        input_payload={"question": "кто истец"},
        output_payload={"status": "ok"},
    )

    assert len(fake_root.created_events) == 1
    payload = fake_root.created_events[0]
    assert payload["name"] == "request_received"
    assert payload["metadata"]["assistant_type"] == "case_assistant"
    assert payload["input"]["question"] == "кто истец"
    assert payload["output"]["status"] == "ok"
    assert fake_root.last_event is not None
    # Langfuse create_event already finalizes event lifecycle.
    assert fake_root.last_event.ended is False


def test_update_trace_updates_root_payload():
    fake_root = _FakeRootObservation()
    ctx = TraceContext(
        trace_id="b" * 32,
        started_at=0.0,
        name="assistant_chat_v2",
        metadata={"mode": "case_assistant"},
        root_observation=fake_root,
    )

    update_trace(
        ctx,
        metadata={"status": "success"},
        output_payload={"response_preview": "ok"},
    )

    assert len(fake_root.updated_payloads) == 1
    payload = fake_root.updated_payloads[0]
    assert payload["output"]["response_preview"] == "ok"
    assert payload["metadata"]["status"] == "success"


class _FakeManualRoot:
    def __init__(self) -> None:
        self.created_events = []
        self.updated_payloads = []
        self.ended = False
        self.last_event = None

    def create_event(self, **kwargs):
        self.created_events.append(kwargs)
        self.last_event = _FakeEvent()
        return self.last_event

    def update(self, **kwargs):
        self.updated_payloads.append(kwargs)
        return self

    def end(self) -> None:
        self.ended = True

    def start_observation(self, **kwargs):
        return _FakeManualRoot()


class _FakeLangfuseClient:
    def __init__(self, root: _FakeManualRoot) -> None:
        self.root = root
        self.start_calls = []

    def start_observation(self, **kwargs):
        self.start_calls.append(kwargs)
        return self.root


def test_create_trace_context_uses_manual_start_observation(monkeypatch):
    fake_root = _FakeManualRoot()
    fake_client = _FakeLangfuseClient(fake_root)
    monkeypatch.setattr(
        "app.services.observability.langfuse_service.get_langfuse_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "app.services.observability.langfuse_service.LANGFUSE_SDK_AVAILABLE",
        True,
    )

    ctx = create_trace_context(
        name="assistant_chat_v2",
        trace_id="c" * 32,
        user_id="user-1",
        session_id="sess-1",
        metadata={"feature": "case_assistant"},
        tags=["assistant"],
        input_payload={"question": "test"},
    )

    assert ctx.user_id == "user-1"
    assert ctx.session_id == "sess-1"
    assert ctx.root_observation is fake_root
    assert len(fake_client.start_calls) == 1
    assert fake_client.start_calls[0]["trace_context"]["trace_id"] == "c" * 32
    assert fake_root.updated_payloads
    assert fake_root.updated_payloads[0]["metadata"]["user_id"] == "user-1"


def test_end_trace_closes_manual_root_without_otel_scope(monkeypatch):
    fake_root = _FakeManualRoot()
    ctx = TraceContext(
        trace_id="d" * 32,
        started_at=0.0,
        name="assistant_chat_v2",
        metadata={},
        root_observation=fake_root,
    )
    monkeypatch.setattr(
        "app.services.observability.langfuse_service.flush_langfuse",
        lambda: None,
    )

    end_trace(ctx, status="success", output_payload={"sse_chars": 42})

    assert fake_root.ended is True
    assert ctx.root_observation is None


def test_start_trace_attribute_scope_updates_context_without_propagate(monkeypatch):
    fake_root = _FakeManualRoot()
    ctx = TraceContext(
        trace_id="e" * 32,
        started_at=0.0,
        name="chat_orchestrator",
        metadata={},
        root_observation=fake_root,
    )
    token = set_active_trace_context(ctx)
    try:
        scope = start_trace_attribute_scope(
            session_id="sess-new",
            user_id="user-new",
            tags=["case_assistant"],
        )
        with scope:
            active = get_active_trace_context()
            assert active is not None
            assert active.session_id == "sess-new"
            assert active.user_id == "user-new"
    finally:
        from app.services.observability.langfuse_service import reset_active_trace_context

        reset_active_trace_context(token)

    assert fake_root.updated_payloads
    assert fake_root.updated_payloads[-1]["metadata"]["session_id"] == "sess-new"
