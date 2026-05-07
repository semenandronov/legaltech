"""Bridge deepagents/LangGraph streaming parts into Workflow ExecutionEvents."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from app.services.workflows.events import ExecutionEvent

MAX_TODOS_IN_SSE = 48


@dataclass
class DeepAgentsStreamState:
    step_counter: int = 0
    current_step_id: Optional[str] = None

    def next_step_id(self) -> str:
        self.step_counter += 1
        self.current_step_id = f"da_step_{self.step_counter}"
        return self.current_step_id


def _now() -> datetime:
    return datetime.utcnow()


def _normalize_stream_parts(raw: Any) -> List[dict]:
    """Coerce LangGraph v2 / subgraph stream chunks into ``{type, ns, data}`` dicts."""
    if isinstance(raw, dict):
        ptype = raw.get("type")
        if ptype in ("updates", "custom", "messages"):
            return [raw]
        # Bare node-update mapping (no envelope)
        if ptype is None and raw:
            return [{"type": "updates", "ns": (), "data": raw}]
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        # LangGraph multi-mode stream can emit (mode, chunk) tuples.
        if isinstance(raw[0], str) and raw[0] in ("updates", "custom", "messages"):
            return [{"type": raw[0], "ns": (), "data": raw[1]}]
        ns = raw[0]
        inner = raw[1]
        if isinstance(inner, dict):
            if inner.get("type") in ("updates", "custom", "messages"):
                d = dict(inner)
                d.setdefault("ns", ns if isinstance(ns, tuple) else ())
                return [d]
            for mode in ("updates", "custom"):
                if mode in inner and inner[mode] is not None:
                    return [{"type": mode, "ns": ns if isinstance(ns, tuple) else (), "data": inner[mode]}]
            if "messages" in inner and inner["messages"] is not None:
                return [{"type": "messages", "ns": ns if isinstance(ns, tuple) else (), "data": inner["messages"]}]
            # Often: { node_name: partial_state, ... }
            if any(isinstance(v, dict) for v in inner.values()):
                return [{"type": "updates", "ns": ns if isinstance(ns, tuple) else (), "data": inner}]
    return []


def _extract_todos_raw_from_updates(data: Any) -> Optional[List[Any]]:
    """Find the richest ``todos`` list inside a LangGraph ``updates`` payload."""
    if not isinstance(data, dict):
        return None
    best: Optional[List[Any]] = None

    def consider(obj: Any, depth: int = 0) -> None:
        nonlocal best
        if depth > 8:
            return
        if isinstance(obj, dict):
            t = obj.get("todos")
            if isinstance(t, list) and len(t) > (len(best) if best else 0):
                best = t
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    consider(v, depth + 1)
        elif isinstance(obj, list):
            for el in obj:
                consider(el, depth + 1)

    consider(data)
    # DeepAgents / LangGraph often emits { "node_name": { ..., "todos": [...] } } without nesting
    if not best:
        for _node_key, node_val in data.items():
            if isinstance(node_val, dict):
                t = node_val.get("todos")
                if isinstance(t, list) and len(t) > (len(best) if best else 0):
                    best = t
    return best


def _coerce_stream_envelopes(raw_part: Any) -> List[dict]:
    """Like :func:`_normalize_stream_parts` plus a last-resort pass-through for typed dicts."""
    parsed = _normalize_stream_parts(raw_part)
    if parsed:
        return parsed
    if isinstance(raw_part, dict) and raw_part.get("type") in ("updates", "custom", "messages"):
        return [raw_part]
    return []


def _extract_message_texts(data: Any) -> List[str]:
    """Best-effort extraction of assistant text chunks from messages stream payloads."""
    out: List[str] = []

    def add_text(value: Any) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text:
                out.append(text)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    # Common OpenAI/LangChain content block shape.
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        add_text(item.get("text"))
                    elif isinstance(item.get("content"), str):
                        add_text(item.get("content"))
                elif isinstance(item, str):
                    add_text(item)

    def walk(obj: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if hasattr(obj, "content"):
            add_text(getattr(obj, "content"))
        if hasattr(obj, "text"):
            add_text(getattr(obj, "text"))
        if isinstance(obj, dict):
            role = str(obj.get("role") or obj.get("type") or "").lower()
            if "assistant" in role or role in {"ai", "message"}:
                add_text(obj.get("content"))
                add_text(obj.get("text"))
            else:
                # Some stream payloads do not include role at this level.
                add_text(obj.get("content"))
                add_text(obj.get("text"))
            for v in obj.values():
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(data)

    deduped: List[str] = []
    seen: set[str] = set()
    for item in out:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _todo_completion_percent(todos_norm: List[Dict[str, str]]) -> int:
    if not todos_norm:
        return 0
    done = 0
    for item in todos_norm:
        st = str(item.get("status") or "").lower()
        if "complete" in st or st in ("done", "completed"):
            done += 1
    return int(round(100 * done / len(todos_norm)))


def _normalize_todo_items(raw: List[Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw[:MAX_TODOS_IN_SSE]:
        if item is None:
            continue
        if hasattr(item, "content") and hasattr(item, "status"):
            st = getattr(item, "status", "pending") or "pending"
            if hasattr(st, "value"):
                st = getattr(st, "value", st)
            st_str = str(st)
            if "." in st_str:
                st_str = st_str.split(".")[-1]
            out.append(
                {
                    "content": str(getattr(item, "content", "") or ""),
                    "status": st_str.lower(),
                }
            )
            continue
        if isinstance(item, dict):
            content = item.get("content") or item.get("task") or item.get("text")
            status = item.get("status") or item.get("state") or "pending"
            if hasattr(status, "value"):
                status = getattr(status, "value", status)
            status_str = str(status)
            if "." in status_str:
                status_str = status_str.split(".")[-1]
            if content is not None:
                out.append({"content": str(content), "status": status_str.lower()})
            continue
        if isinstance(item, str):
            out.append({"content": item, "status": "pending"})
    return out


async def stream_parts_to_events(
    *,
    execution_id: str,
    parts: Any,
) -> AsyncIterator[ExecutionEvent]:
    """
    Convert deepagents .stream(v2) parts into ExecutionEvent stream.

    Expected part shape (v2): { "type": str, "ns": tuple, "data": ... }
    With ``subgraphs=True``, parts may be ``(namespace, inner)`` tuples — we unwrap them.
    """
    state = DeepAgentsStreamState()
    last_todos_signature: Optional[str] = None

    yield ExecutionEvent(
        event_type="planning_started",
        execution_id=execution_id,
        timestamp=_now(),
        message="DeepAgents: старт планирования/исполнения",
        progress_percent=0,
    )

    async for raw_part in parts:
        for part in _coerce_stream_envelopes(raw_part):
            ptype = part.get("type")
            data = part.get("data")

            # Custom tool progress events from get_stream_writer in our harness.
            if ptype == "custom" and isinstance(data, dict):
                if data.get("type") == "tool_started":
                    step_id = state.next_step_id()
                    yield ExecutionEvent(
                        event_type="tool_reasoned",
                        execution_id=execution_id,
                        step_id=step_id,
                        timestamp=_now(),
                        data={
                            "selected_tool": data.get("tool"),
                            "decision_reason": "DeepAgents tool call",
                            "required_inputs": [],
                            "confidence": 0.75,
                        },
                        message=f"Выбран инструмент {data.get('tool')}",
                    )
                    yield ExecutionEvent(
                        event_type="step_started",
                        execution_id=execution_id,
                        step_id=step_id,
                        timestamp=_now(),
                        data={"tool": data.get("tool"), "params_preview": data.get("params_preview")},
                        message=f"Выполнение инструмента: {data.get('tool')}",
                    )
                    continue

                if data.get("type") == "tool_completed":
                    step_id = state.current_step_id or state.next_step_id()
                    success = bool(data.get("success", False))
                    if success:
                        yield ExecutionEvent(
                            event_type="step_completed",
                            execution_id=execution_id,
                            step_id=step_id,
                            timestamp=_now(),
                            data={
                                "success": True,
                                "summary": data.get("output_summary", ""),
                                "tool": data.get("tool"),
                                "result": data.get("result"),
                            },
                            message=f"Шаг завершён: {data.get('tool')}",
                        )
                    else:
                        yield ExecutionEvent(
                            event_type="step_failed",
                            execution_id=execution_id,
                            step_id=step_id,
                            timestamp=_now(),
                            data={
                                "error": data.get("error") or "tool_failed",
                                "tool": data.get("tool"),
                                "result": data.get("result"),
                            },
                            message=f"Ошибка в шаге: {data.get('tool')}",
                        )
                    continue

            if ptype == "updates" and isinstance(data, dict):
                todos_raw = _extract_todos_raw_from_updates(data)
                if todos_raw:
                    todos_norm = _normalize_todo_items(todos_raw)
                    if todos_norm:
                        sig = json.dumps(todos_norm, ensure_ascii=True, sort_keys=True)
                        if sig != last_todos_signature:
                            last_todos_signature = sig
                            yield ExecutionEvent(
                                event_type="agent_todos_updated",
                                execution_id=execution_id,
                                timestamp=_now(),
                                data={"todos": todos_norm},
                                message="Подзадачи агента обновлены",
                                progress_percent=_todo_completion_percent(todos_norm),
                            )
                        continue

                yield ExecutionEvent(
                    event_type="status",
                    execution_id=execution_id,
                    timestamp=_now(),
                    data={"deepagents_updates": list(data.keys())[:12]},
                    message="DeepAgents: update",
                )
                continue

            if ptype == "messages":
                for chunk in _extract_message_texts(data):
                    yield ExecutionEvent(
                        event_type="assistant_message",
                        execution_id=execution_id,
                        timestamp=_now(),
                        data={"content": chunk},
                        message="DeepAgents: assistant message chunk",
                    )
                continue

        # Unknown stream envelopes are ignored by design.

