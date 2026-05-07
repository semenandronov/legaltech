from app.services.observability.langfuse_service import TraceContext, trace_event, update_trace


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
