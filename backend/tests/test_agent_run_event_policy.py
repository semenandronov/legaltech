"""Tests for agent run SSE persistence policy."""
from app.services.agent_runs.event_policy import should_persist_stream_event
from app.services.agent_runs.schemas import AgentRunEventType, AgentRunStreamEvent


def test_persist_tool_events_and_final_text():
    assert should_persist_stream_event(
        AgentRunStreamEvent(type=AgentRunEventType.tool_started, run_id="r1")
    )
    assert should_persist_stream_event(
        AgentRunStreamEvent(type=AgentRunEventType.tool_completed, run_id="r1")
    )
    assert should_persist_stream_event(
        AgentRunStreamEvent(type=AgentRunEventType.text_delta, run_id="r1", data={"text": "ok"})
    )


def test_persist_todos_updated():
    assert should_persist_stream_event(
        AgentRunStreamEvent(
            type=AgentRunEventType.todos_updated,
            run_id="r1",
            data={"todos": [{"content": "Шаг 1", "status": "pending"}]},
        )
    )


def test_skip_run_started():
    assert not should_persist_stream_event(
        AgentRunStreamEvent(type=AgentRunEventType.run_started, run_id="r1")
    )
