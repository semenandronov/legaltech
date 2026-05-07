"""Накопление шагов reasoning из SSE для сохранения в БД (как на фронте)."""
from __future__ import annotations

from typing import Any, Dict, List


def merge_reasoning_dict(steps: List[Dict[str, Any]], data: Dict[str, Any]) -> None:
    """Обновить список шагов по одному событию type=reasoning (как в AssistantChatPage)."""
    if data.get("type") != "reasoning":
        return
    phase = data.get("phase")
    content = data.get("content")
    if phase is None or content is None:
        return
    step = data.get("step")
    if step is None:
        step = data.get("stepNumber") or (len(steps) + 1)
    total_steps = (
        data.get("totalSteps")
        or data.get("total_steps")
        or data.get("totalStepsNumber")
        or 4
    )
    try:
        step_int = int(step) if not isinstance(step, int) else step
    except (TypeError, ValueError):
        step_int = len(steps) + 1
    try:
        ts_int = int(total_steps) if not isinstance(total_steps, int) else total_steps
    except (TypeError, ValueError):
        ts_int = 4
    new_step = {
        "phase": phase,
        "step": step_int,
        "totalSteps": ts_int,
        "content": content,
    }
    idx = next(
        (
            i
            for i, s in enumerate(steps)
            if s.get("phase") == new_step["phase"] and s.get("step") == new_step["step"]
        ),
        -1,
    )
    if idx >= 0:
        steps[idx] = new_step
    else:
        steps.append(new_step)


def merge_reasoning_from_sse_event_line(event_line: str, steps: List[Dict[str, Any]]) -> None:
    """Разобрать строку SSE `data: {...}` и при type=reasoning смержить в steps."""
    if "data:" not in event_line or "reasoning" not in event_line:
        return
    import json

    try:
        raw = event_line.replace("data: ", "", 1).strip()
        if not raw:
            return
        data = json.loads(raw)
        merge_reasoning_dict(steps, data)
    except Exception:
        return
