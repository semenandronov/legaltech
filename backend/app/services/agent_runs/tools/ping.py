"""Health-check tool for validating the agent runtime end-to-end."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from app.services.agent_runs.schemas import PingToolInput, PingToolOutput

logger = logging.getLogger(__name__)


def build_ping_tool(*, run_id: str, on_tool_completed: Callable[[], None] | None = None) -> Any:
    """Factory: binds run_id and optional metrics hook."""

    @tool("agent_ping", args_schema=PingToolInput)
    async def agent_ping(message: str) -> Dict[str, Any]:
        """Проверочный инструмент: эхо-ответ для валидации tool-calling и SSE."""
        writer = None
        try:
            writer = get_stream_writer()
        except Exception:
            writer = None

        if writer is not None:
            writer({"type": "tool_started", "tool": "agent_ping", "params_preview": {"message": message[:120]}})

        output = PingToolOutput(status="success", echo=message.strip(), run_id=run_id)
        payload = output.model_dump()

        if writer is not None:
            writer(
                {
                    "type": "tool_completed",
                    "tool": "agent_ping",
                    "success": True,
                    "output_summary": payload["echo"][:500],
                }
            )

        if on_tool_completed is not None:
            on_tool_completed()

        logger.info("agent_ping completed for run_id=%s", run_id)
        return payload

    return agent_ping
