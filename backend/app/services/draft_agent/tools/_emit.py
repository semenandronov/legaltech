"""SSE emission for draft agent tools (LangGraph stream writer)."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from langgraph.config import get_stream_writer


def get_stream_writer_safe() -> Optional[Callable[[Dict[str, Any]], None]]:
    try:
        return get_stream_writer()
    except Exception:
        return None


def emit_tool_started(tool_name: str, params_preview: Dict[str, Any]) -> None:
    writer = get_stream_writer_safe()
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
    writer = get_stream_writer_safe()
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
