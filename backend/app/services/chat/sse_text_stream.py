"""
SSE text streaming contract for assistant chat.

- ``textDelta`` events append incremental pieces (from llm_streaming custom channel).
- ``content_sync`` replaces the full visible answer with the canonical post-processed text.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


def _parse_sse_data_line(event: str) -> Optional[Dict[str, Any]]:
    raw = (event or "").strip()
    if not raw.startswith("data:"):
        return None
    payload = raw.split(":", 1)[1].strip()
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def extract_text_delta_piece(event: str) -> str:
    """Return incremental text from an SSE event, or empty string."""
    data = _parse_sse_data_line(event)
    if not data:
        return ""
    if data.get("type") == "content_sync":
        return ""
    delta = data.get("textDelta")
    if delta is None and data.get("type") in ("text_delta", "text-delta"):
        delta = data.get("text_delta")
    return str(delta) if isinstance(delta, str) and delta else ""


def extract_content_sync(event: str) -> Optional[str]:
    """Return canonical replacement text from content_sync, or None."""
    data = _parse_sse_data_line(event)
    if not data or data.get("type") != "content_sync":
        return None
    content = data.get("content")
    return content if isinstance(content, str) else None


def apply_sse_event_to_text(accumulated: str, event: str) -> str:
    """
    Update accumulated assistant text from one SSE line.

    content_sync wins over prior streamed deltas; textDelta appends incrementally.
    """
    synced = extract_content_sync(event)
    if synced is not None:
        return synced
    piece = extract_text_delta_piece(event)
    if piece:
        return (accumulated or "") + piece
    return accumulated
