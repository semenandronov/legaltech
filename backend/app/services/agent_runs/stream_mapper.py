"""Map LangGraph / deepagents stream parts to typed AgentRunStreamEvent."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.services.agent_runs.schemas import AgentRunEventType, AgentRunStreamEvent, AgentTodoItem

MAX_TODOS = 48


def _normalize_parts(raw: Any) -> List[dict]:
    if isinstance(raw, dict):
        ptype = raw.get("type")
        if ptype in ("updates", "custom", "messages"):
            return [raw]
        if ptype is None and raw:
            return [{"type": "updates", "ns": (), "data": raw}]
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
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
    return []


def _extract_todos(data: Any) -> Optional[List[dict]]:
    if not isinstance(data, dict):
        return None
    best: Optional[List[Any]] = None

    def walk(obj: Any, depth: int = 0) -> None:
        nonlocal best
        if depth > 8:
            return
        if isinstance(obj, dict):
            todos = obj.get("todos")
            if isinstance(todos, list) and len(todos) > (len(best) if best else 0):
                best = todos
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(data)
    if not best:
        return None
    normalized: List[dict] = []
    for item in best[:MAX_TODOS]:
        if isinstance(item, dict):
            normalized.append(
                {
                    "content": str(item.get("content") or item.get("task") or ""),
                    "status": str(item.get("status") or "pending"),
                }
            )
        else:
            normalized.append({"content": str(item), "status": "pending"})
    return normalized or None


def _extract_interrupt(data: Any) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    if "__interrupt__" in data:
        return {"payload": data["__interrupt__"]}
    for value in data.values():
        if isinstance(value, dict) and "__interrupt__" in value:
            return {"payload": value["__interrupt__"]}
    return None


def map_stream_part(run_id: str, raw_part: Any) -> Iterable[AgentRunStreamEvent]:
    for part in _normalize_parts(raw_part):
        ptype = part.get("type")
        data = part.get("data")

        if ptype == "custom" and isinstance(data, dict):
            custom_type = data.get("type")
            if custom_type == "tool_started":
                yield AgentRunStreamEvent(
                    type=AgentRunEventType.tool_started,
                    run_id=run_id,
                    data={
                        "tool": data.get("tool"),
                        "params_preview": data.get("params_preview"),
                    },
                )
            elif custom_type == "tool_completed":
                payload: Dict[str, Any] = {
                    "tool": data.get("tool"),
                    "success": data.get("success"),
                    "output_summary": data.get("output_summary"),
                }
                if data.get("artifact"):
                    payload["artifact"] = data.get("artifact")
                yield AgentRunStreamEvent(
                    type=AgentRunEventType.tool_completed,
                    run_id=run_id,
                    data=payload,
                )
            continue

        if ptype == "updates":
            interrupt = _extract_interrupt(data)
            if interrupt:
                yield AgentRunStreamEvent(
                    type=AgentRunEventType.interrupt,
                    run_id=run_id,
                    data=interrupt,
                )

            todos = _extract_todos(data)
            if todos:
                yield AgentRunStreamEvent(
                    type=AgentRunEventType.todos_updated,
                    run_id=run_id,
                    data={"todos": [AgentTodoItem(**t).model_dump() for t in todos]},
                )

        if ptype == "messages" and data is not None:
            text = _message_text(data)
            if text:
                yield AgentRunStreamEvent(
                    type=AgentRunEventType.text_delta,
                    run_id=run_id,
                    data={"text": text},
                )


def _content_blocks_to_text(content: Any) -> str:
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
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _message_text(data: Any) -> str:
    if isinstance(data, str):
        return data
    # LangChain AIMessage / AIMessageChunk instance
    if hasattr(data, "content"):
        text = _content_blocks_to_text(getattr(data, "content", None))
        if text:
            return text
    if isinstance(data, list):
        chunks: List[str] = []
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                chunk = _message_text(item[1])
                if chunk:
                    chunks.append(chunk)
            else:
                chunk = _message_text(item)
                if chunk:
                    chunks.append(chunk)
        return "".join(chunks)
    if isinstance(data, dict):
        content = data.get("content")
        return _content_blocks_to_text(content)
    return ""
