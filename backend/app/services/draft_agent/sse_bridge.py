"""Map draft agent LangGraph stream parts to chat SSE strings."""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, List, Optional

from app.services.agent_runs.stream_mapper import map_stream_part
from app.services.chat.events import SSESerializer

logger = logging.getLogger(__name__)

# Human-readable labels for UI
_TOOL_LABELS = {
    "draft_case_search": "Поиск по делу",
    "draft_legal_search": "Правовой справочник",
    "draft_court_practice_search": "Судебная практика",
    "draft_calculator": "Финансовый калькулятор",
    "draft_write_document": "Создание документа",
    "write_todos": "План работы",
    "agent_case_search": "Поиск по делу",
    "agent_legal_corpus_search": "Правовой справочник",
}


def _tool_label(name: str) -> str:
    return _TOOL_LABELS.get(name, name)


def _extract_todos_from_part(part: Any) -> Optional[List[dict]]:
    from app.services.agent_runs.stream_mapper import _extract_todos

    if isinstance(part, dict) and part.get("type") == "updates":
        return _extract_todos(part.get("data"))
    for normalized in _normalize_raw(part):
        if normalized.get("type") == "updates":
            todos = _extract_todos(normalized.get("data"))
            if todos:
                return todos
    return None


def _normalize_raw(raw: Any) -> List[dict]:
    from app.services.agent_runs.stream_mapper import _normalize_parts

    return _normalize_parts(raw)


def _document_from_artifact(artifact: dict, *, case_id: str) -> Optional[dict]:
    if not isinstance(artifact, dict):
        return None
    doc_id = str(artifact.get("id") or artifact.get("document_id") or "").strip()
    if not doc_id:
        return None
    return {
        "id": doc_id,
        "title": str(artifact.get("title") or "Новый документ"),
        "case_id": case_id,
        "preview": str(artifact.get("preview") or "")[:500],
        "editor_path": artifact.get("path") or artifact.get("editor_path"),
    }


class _ToolTracker:
    """Track running tools to emit paired tool_call SSE events."""

    def __init__(self) -> None:
        self._running: set[str] = set()

    def on_started(self, tool: str, preview: dict) -> Iterable[str]:
        label = _tool_label(tool)
        self._running.add(tool)
        preview_text = ""
        if isinstance(preview, dict):
            q = preview.get("query") or preview.get("reason") or preview.get("title")
            if q:
                preview_text = str(q)[:200]
        yield SSESerializer.tool_call(label, "running", input=preview_text or None)

    def on_completed(self, tool: str, *, success: bool, summary: str, artifact: Optional[dict] = None) -> Iterable[str]:
        label = _tool_label(tool)
        self._running.discard(tool)
        status = "completed" if success else "error"
        yield SSESerializer.tool_call(label, status, output=summary[:500] if summary else None)
        if success and tool in ("draft_write_document", "agent_draft") and artifact:
            return
        return


def map_draft_stream_to_sse(
    *,
    session_id: str,
    case_id: str,
    raw_part: Any,
    tracker: _ToolTracker,
    todos_sent: set[str],
) -> Iterable[str]:
    """Convert one astream chunk to zero or more SSE lines."""
    # Custom tool events from LangGraph writer
    for norm in _normalize_raw(raw_part):
        if norm.get("type") != "custom":
            continue
        data = norm.get("data")
        if not isinstance(data, dict):
            continue
        ctype = data.get("type")
        tool = str(data.get("tool") or "")
        if ctype == "tool_started" and tool:
            yield from tracker.on_started(tool, data.get("params_preview") or {})
        elif ctype == "tool_completed" and tool:
            artifact = data.get("artifact") if isinstance(data.get("artifact"), dict) else None
            yield from tracker.on_completed(
                tool,
                success=bool(data.get("success")),
                summary=str(data.get("output_summary") or ""),
                artifact=artifact,
            )
            if artifact and tool == "draft_write_document":
                doc = _document_from_artifact(artifact, case_id=case_id)
                if doc:
                    yield f"data: {json.dumps({'type': 'document-card', 'data': doc}, ensure_ascii=False)}\n\n"

    # Todos from updates
    todos = _extract_todos_from_part(raw_part)
    if todos:
        key = json.dumps(todos, ensure_ascii=False, sort_keys=True)
        if key not in todos_sent:
            todos_sent.add(key)
            yield f"data: {json.dumps({'type': 'draft_todos', 'todos': todos}, ensure_ascii=False)}\n\n"
            for i, item in enumerate(todos):
                content = str(item.get("content") or "").strip()
                status = str(item.get("status") or "pending")
                if not content:
                    continue
                yield SSESerializer.assistant_activity(
                    step_id=f"draft_todo_{i}",
                    phase=f"draft_todo_{i}",
                    step=i + 1,
                    total_steps=len(todos),
                    label="План",
                    content=content,
                    status="completed" if status == "completed" else ("running" if status == "in_progress" else "pending"),
                )

    # Fallback: reuse agent run mapper for any extra events (no text_delta — final only)
    run_id = f"draft-{session_id}"
    for event in map_stream_part(run_id, raw_part):
        if event.type.value == "todos_updated" and event.data:
            todos = event.data.get("todos") or []
            key = json.dumps(todos, ensure_ascii=False, sort_keys=True)
            if key not in todos_sent:
                todos_sent.add(key)
                yield f"data: {json.dumps({'type': 'draft_todos', 'todos': todos}, ensure_ascii=False)}\n\n"
