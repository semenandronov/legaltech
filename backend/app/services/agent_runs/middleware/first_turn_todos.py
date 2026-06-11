"""Force write_todos on the first model call before any other tools."""
from __future__ import annotations

from typing import Any, Callable

from langchain.agents.middleware.types import AgentMiddleware

WRITE_TODOS_TOOL = "write_todos"
WRITE_TODOS_TOOL_CHOICE = {"type": "function", "function": {"name": WRITE_TODOS_TOOL}}


def _tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        name = tool.get("name")
        return name if isinstance(name, str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def _has_workflow_plan(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    todos = state.get("todos")
    if isinstance(todos, list) and len(todos) > 0:
        return True
    return False


class FirstTurnWriteTodosMiddleware(AgentMiddleware[Any, Any, Any]):
    """First model call may only invoke write_todos (tool_choice enforcement)."""

    async def awrap_model_call(self, request, handler):
        if _has_workflow_plan(request.state):
            return await handler(request)

        planner_tools = [t for t in request.tools if _tool_name(t) == WRITE_TODOS_TOOL]
        if not planner_tools:
            return await handler(request)

        planned = request.override(
            tools=planner_tools,
            tool_choice=WRITE_TODOS_TOOL_CHOICE,
        )
        return await handler(planned)

    def wrap_model_call(self, request, handler):
        if _has_workflow_plan(request.state):
            return handler(request)

        planner_tools = [t for t in request.tools if _tool_name(t) == WRITE_TODOS_TOOL]
        if not planner_tools:
            return handler(request)

        planned = request.override(
            tools=planner_tools,
            tool_choice=WRITE_TODOS_TOOL_CHOICE,
        )
        return handler(planned)
