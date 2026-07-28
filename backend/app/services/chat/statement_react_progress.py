"""SSE progress for statement ReAct (matches AssistantActivityEvent contract)."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

ProgressCallback = Callable[[Dict[str, Any]], None]

_REACT_TOTAL_STEPS = 14


def emit_statement_react_progress(
    callback: Optional[ProgressCallback],
    *,
    step_id: str,
    phase: str,
    label: str,
    detail: str = "",
    status: str = "running",
    step: int = 1,
) -> None:
    if not callback:
        return
    detail_text = (detail or "").strip()
    content = f"{label}: {detail_text}" if detail_text else label
    callback(
        {
            "step_id": step_id,
            "phase": phase,
            "step": step,
            "totalSteps": _REACT_TOTAL_STEPS,
            "label": label,
            "detail": detail_text or None,
            "content": content,
            "status": status,
        }
    )
