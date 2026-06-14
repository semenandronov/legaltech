"""Tests for draft agent SSE bridge."""
from __future__ import annotations

from app.services.draft_agent.sse_bridge import _ToolTracker, map_draft_stream_to_sse


def test_map_custom_tool_started_to_sse():
    tracker = _ToolTracker()
    events = list(
        map_draft_stream_to_sse(
            session_id="s1",
            case_id="c1",
            raw_part={"type": "custom", "data": {"type": "tool_started", "tool": "draft_court_practice_search", "params_preview": {"query": "неустойка"}}},
            tracker=tracker,
            todos_sent=set(),
        )
    )
    assert any("tool_call" in e and "running" in e for e in events)
    assert any("Судебная практика" in e for e in events)


def test_map_todos_updated_to_draft_todos_sse():
    tracker = _ToolTracker()
    sent: set[str] = set()
    part = {
        "type": "updates",
        "data": {"todos": [{"content": "Найти договор", "status": "pending"}]},
    }
    events = list(
        map_draft_stream_to_sse(
            session_id="s1",
            case_id="c1",
            raw_part=part,
            tracker=tracker,
            todos_sent=sent,
        )
    )
    assert any("draft_todos" in e for e in events)
