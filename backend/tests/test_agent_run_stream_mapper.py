"""Unit tests for agent run SSE stream mapping."""
from app.services.agent_runs.schemas import AgentRunEventType
from app.services.agent_runs.stream_mapper import map_stream_part


def test_map_custom_tool_events():
    run_id = "run-1"
    part = {
        "type": "custom",
        "data": {
            "type": "tool_started",
            "tool": "agent_ping",
            "params_preview": {"message": "hello"},
        },
    }
    events = list(map_stream_part(run_id, part))
    assert len(events) == 1
    assert events[0].type == AgentRunEventType.tool_started
    assert events[0].data["tool"] == "agent_ping"


def test_map_ai_message_chunk_text():
    from langchain_core.messages import AIMessage

    run_id = "run-msg"
    part = {"type": "messages", "data": AIMessage(content="Финальный ответ юристу.")}
    events = list(map_stream_part(run_id, part))
    assert any(e.type == AgentRunEventType.text_delta for e in events)
    delta = next(e for e in events if e.type == AgentRunEventType.text_delta)
    assert "Финальный ответ" in delta.data["text"]


def test_map_todos_from_updates():
    run_id = "run-2"
    part = {
        "type": "updates",
        "data": {
            "agent": {
                "todos": [
                    {"content": "Сверить суммы", "status": "in_progress"},
                    {"content": "Найти практику", "status": "pending"},
                ]
            }
        },
    }
    events = list(map_stream_part(run_id, part))
    assert any(e.type == AgentRunEventType.todos_updated for e in events)
    todos_event = next(e for e in events if e.type == AgentRunEventType.todos_updated)
    assert len(todos_event.data["todos"]) == 2
