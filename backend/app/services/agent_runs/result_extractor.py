"""Extract final assistant answer from LangGraph / LangChain message state."""
from __future__ import annotations

from typing import Any, List, Optional, Sequence


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _message_type_name(msg: Any) -> str:
    if isinstance(msg, dict):
        role = msg.get("role") or msg.get("type") or ""
        return str(role).lower()
    type_name = getattr(msg, "type", None) or msg.__class__.__name__
    return str(type_name).lower()


def _has_tool_calls(msg: Any) -> bool:
    if isinstance(msg, dict):
        tc = msg.get("tool_calls")
        return bool(tc)
    tc = getattr(msg, "tool_calls", None)
    return bool(tc)


def _is_assistant_message(msg: Any) -> bool:
    name = _message_type_name(msg)
    if name in ("ai", "assistant", "aimessage", "aimessagechunk"):
        return True
    if isinstance(msg, dict) and msg.get("role") in ("assistant", "ai"):
        return True
    return "ai" in name and "human" not in name


def _message_content(msg: Any) -> str:
    if isinstance(msg, dict):
        return _content_to_text(msg.get("content"))
    return _content_to_text(getattr(msg, "content", None))


def extract_final_assistant_text(messages: Optional[Sequence[Any]]) -> str:
    """
    Pick the last meaningful assistant reply (not a tool-call-only stub).

    Used when token streaming did not populate result_summary.
    """
    if not messages:
        return ""

    # Prefer last AI message without tool_calls (typical final answer).
    for msg in reversed(list(messages)):
        if not _is_assistant_message(msg):
            continue
        text = _message_content(msg).strip()
        if not text:
            continue
        if not _has_tool_calls(msg):
            return text

    # Fallback: longest non-empty assistant content (e.g. answer after tools).
    best = ""
    for msg in messages:
        if not _is_assistant_message(msg):
            continue
        text = _message_content(msg).strip()
        if len(text) > len(best):
            best = text
    return best


async def extract_final_assistant_from_agent(agent: Any, graph_config: dict) -> str:
    """Read checkpointer state after graph completes."""
    try:
        snapshot = await agent.aget_state(graph_config)
    except Exception:
        return ""
    if not snapshot:
        return ""
    values = getattr(snapshot, "values", None) or {}
    if not isinstance(values, dict):
        return ""
    return extract_final_assistant_text(values.get("messages"))
