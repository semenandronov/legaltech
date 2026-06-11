"""Which agent-run SSE events are persisted to Postgres (source of truth)."""
from __future__ import annotations

from app.services.agent_runs.schemas import AgentRunEventType, AgentRunStreamEvent

# No token streaming: plan (todos) + tools during run; final text once at the end.
PERSISTED_STREAM_EVENT_TYPES = frozenset(
    {
        AgentRunEventType.tool_started,
        AgentRunEventType.tool_completed,
        AgentRunEventType.todos_updated,
        AgentRunEventType.text_delta,
        AgentRunEventType.interrupt,
        AgentRunEventType.run_completed,
        AgentRunEventType.run_failed,
        AgentRunEventType.run_cancelled,
        AgentRunEventType.error,
    }
)


def should_persist_stream_event(event: AgentRunStreamEvent) -> bool:
    return event.type in PERSISTED_STREAM_EVENT_TYPES
