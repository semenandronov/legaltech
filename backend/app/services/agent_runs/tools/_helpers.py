"""Shared helpers for agent run tools."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from langgraph.config import get_stream_writer

from app.config import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


def get_tool_stream_writer() -> Optional[Callable[[Dict[str, Any]], None]]:
    try:
        return get_stream_writer()
    except Exception:
        return None


def emit_tool_started(tool_name: str, params_preview: Dict[str, Any]) -> None:
    writer = get_tool_stream_writer()
    if writer is None:
        return
    writer({"type": "tool_started", "tool": tool_name, "params_preview": params_preview})


def emit_tool_completed(
    tool_name: str,
    *,
    success: bool,
    output_summary: str,
    artifact: Optional[Dict[str, Any]] = None,
) -> None:
    writer = get_tool_stream_writer()
    if writer is None:
        return
    payload: Dict[str, Any] = {
        "type": "tool_completed",
        "tool": tool_name,
        "success": success,
        "output_summary": output_summary[:500],
    }
    if artifact:
        payload["artifact"] = artifact
    writer(payload)


async def run_with_timeout(coro: Awaitable[T], *, label: str) -> T:
    timeout_sec = float(getattr(config, "AGENT_RUNS_TOOL_TIMEOUT_SEC", 120) or 120)
    try:
        return await asyncio.wait_for(coro, timeout=timeout_sec)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} превысил лимит {timeout_sec:.0f} с") from exc
