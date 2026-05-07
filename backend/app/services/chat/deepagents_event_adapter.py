from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.chat.events import SSESerializer
from app.services.workflows.events import ExecutionEvent


class DeepAgentsEventToSSEAdapter:
    """Map workflow/deepagents execution events to chat SSE payloads."""

    @staticmethod
    def to_sse(event: ExecutionEvent) -> Optional[str]:
        event_type = (event.event_type or "").strip().lower()
        data: Dict[str, Any] = event.data or {}

        if event_type == "planning_started":
            return SSESerializer.status(
                "deep_planning_started",
                message=event.message or "Запущено deep-планирование",
                progress_percent=int(event.progress_percent or 0),
            )

        if event_type == "tool_reasoned":
            tool_name = str(data.get("selected_tool") or "tool")
            return SSESerializer.tool_call(name=tool_name, status="running")

        if event_type == "step_started":
            tool_name = str(data.get("tool") or "tool")
            return SSESerializer.reasoning(
                phase="deep_execution",
                step=1,
                total_steps=1,
                content=f"Выполняю инструмент: {tool_name}",
            )

        if event_type == "step_completed":
            tool_name = str(data.get("tool") or "tool")
            summary = str(data.get("summary") or "")[:500]
            return SSESerializer.tool_call(
                name=tool_name,
                status="completed",
                output=summary if summary else None,
            )

        if event_type == "step_failed":
            tool_name = str(data.get("tool") or "tool")
            err = str(data.get("error") or "tool_failed")
            return SSESerializer.tool_call(name=tool_name, status="error", output=err[:500])

        if event_type == "agent_todos_updated":
            todos = data.get("todos") if isinstance(data.get("todos"), list) else []
            return SSESerializer.status(
                "deep_todos_updated",
                todos=todos[:24],
                progress_percent=int(event.progress_percent or 0),
            )

        if event_type == "status":
            payload: Dict[str, Any] = {}
            if event.message:
                payload["message"] = event.message
            if event.progress_percent:
                payload["progress_percent"] = int(event.progress_percent)
            if data:
                payload["details"] = data
            return SSESerializer.status("deep_status", **payload)

        if event_type == "assistant_message":
            content = str(data.get("content") or "").strip()
            if content:
                return SSESerializer.text_delta(content)
            return None

        return None

