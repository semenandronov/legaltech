"""Tests for agent run harness configuration."""
from unittest.mock import MagicMock, patch

from app.services.agent_runs.harness import (
    EXCLUDED_FILESYSTEM_TOOLS,
    AgentRunHarness,
    AgentRunHarnessContext,
)
from app.services.agent_runs.middleware.first_turn_todos import FirstTurnWriteTodosMiddleware


def test_harness_excludes_filesystem_tools():
    ctx = AgentRunHarnessContext(
        user_id="user-1",
        case_id="case-1",
        run_id="run-1",
        file_ids=[],
    )
    harness = AgentRunHarness(ctx)

    with patch("deepagents.create_deep_agent") as mock_create:
        harness.create_agent(checkpointer=MagicMock())
        kwargs = mock_create.call_args.kwargs
        middleware = kwargs.get("middleware") or []

    excluded_sets = [
        getattr(m, "_excluded", None)
        for m in middleware
        if getattr(m, "_excluded", None) is not None
    ]
    assert excluded_sets, "expected _ToolExclusionMiddleware in harness middleware"
    merged = set().union(*excluded_sets)
    assert EXCLUDED_FILESYSTEM_TOOLS.issubset(merged)
    assert any(isinstance(m, FirstTurnWriteTodosMiddleware) for m in middleware)
