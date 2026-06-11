"""Tests for first-turn write_todos enforcement middleware."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent_runs.middleware.first_turn_todos import (
    WRITE_TODOS_TOOL,
    WRITE_TODOS_TOOL_CHOICE,
    FirstTurnWriteTodosMiddleware,
)


def _make_request(*, state, tools, tool_choice=None):
    request = MagicMock()
    request.state = state
    request.tools = tools
    request.tool_choice = tool_choice
    request.override = MagicMock(side_effect=lambda **kwargs: {**kwargs, "state": state, "tools": kwargs.get("tools", tools)})
    return request


@pytest.mark.asyncio
async def test_first_turn_forces_write_todos_only():
    middleware = FirstTurnWriteTodosMiddleware()
    write_todos = MagicMock()
    write_todos.name = WRITE_TODOS_TOOL
    search = MagicMock()
    search.name = "agent_case_search"

    request = _make_request(state={"todos": []}, tools=[write_todos, search])
    handler = AsyncMock(return_value="ok")

    await middleware.awrap_model_call(request, handler)

    request.override.assert_called_once_with(
        tools=[write_todos],
        tool_choice=WRITE_TODOS_TOOL_CHOICE,
    )
    handler.assert_awaited_once()
    planned = handler.await_args.args[0]
    assert planned["tools"] == [write_todos]
    assert planned["tool_choice"] == WRITE_TODOS_TOOL_CHOICE


@pytest.mark.asyncio
async def test_skips_when_plan_exists():
    middleware = FirstTurnWriteTodosMiddleware()
    request = _make_request(
        state={"todos": [{"content": "Шаг 1", "status": "pending"}]},
        tools=[],
    )
    handler = AsyncMock(return_value="ok")

    await middleware.awrap_model_call(request, handler)

    request.override.assert_not_called()
    handler.assert_awaited_once_with(request)
