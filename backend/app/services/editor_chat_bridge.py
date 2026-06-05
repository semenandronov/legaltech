"""
Sync bridge: collect EditorHandler SSE stream into DocumentChatResponse-shaped dict.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.user import User
from app.services.chat.editor_handler import EditorHandler
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)


def _parse_sse_data_lines(chunk: str) -> List[Dict[str, Any]]:
    """Extract JSON objects from SSE chunk lines."""
    payloads: List[Dict[str, Any]] = []
    for line in (chunk or "").split("\n"):
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            payloads.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return payloads


def _normalize_citations(raw: List[Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "file": str(item.get("file") or item.get("filename") or "Документ дела"),
                "file_id": str(item.get("file_id") or item.get("id") or ""),
            }
        )
    return out[:10]


def _attach_selection_to_edits(
    edits: List[Dict[str, Any]],
    *,
    selected_text: Optional[str],
    selection_range: Optional[Dict[str, int]],
) -> List[Dict[str, Any]]:
    if not edits:
        return edits
    result = []
    for edit in edits:
        e = dict(edit)
        if selection_range and not e.get("selection_range"):
            e["selection_range"] = selection_range
        if selected_text and not e.get("original_text"):
            e["original_text"] = selected_text
            e["found_in_document"] = True
        if not e.get("id"):
            e["id"] = f"edit-{uuid.uuid4().hex[:8]}"
        result.append(e)
    return result


class EditorChatBridge:
    """Collects LangGraph SSE from EditorHandler into a single JSON response."""

    def __init__(self, db: Session, rag_service: Optional[RAGService] = None):
        self.db = db
        self.rag_service = rag_service or RAGService()

    async def run(
        self,
        *,
        case_id: str,
        user: User,
        document_id: str,
        document_content: str,
        question: str,
        mode: str = "ask",
        selected_text: Optional[str] = None,
        selection_range: Optional[Dict[str, int]] = None,
        attached_file_ids: Optional[List[str]] = None,
        deep_think: bool = False,
        legal_research: bool = False,
    ) -> Dict[str, Any]:
        editor_mode_hint = mode if mode in ("ask", "edit", "draft") else "ask"
        handler = EditorHandler(self.rag_service, self.db)

        answer_parts: List[str] = []
        structured_edits: List[Dict[str, Any]] = []
        citations: List[Dict[str, str]] = []
        edited_content: Optional[str] = None
        suggestions: List[str] = []
        error_message: Optional[str] = None

        async for chunk in handler.handle(
            case_id=case_id,
            question=question,
            current_user=user,
            document_id=document_id or "",
            document_context=document_content or "",
            selected_text=selected_text,
            editor_mode_hint=editor_mode_hint,
            attached_file_ids=attached_file_ids,
            deep_think=deep_think,
            legal_research=legal_research,
        ):
            for payload in _parse_sse_data_lines(chunk):
                if payload.get("error"):
                    error_message = str(payload.get("error"))
                    continue

                if "structured_edits" in payload:
                    raw_edits = payload.get("structured_edits") or []
                    if isinstance(raw_edits, list):
                        structured_edits = raw_edits

                if payload.get("type") == "edited_content" or payload.get("edited_content"):
                    edited_content = payload.get("edited_content") or edited_content

                if payload.get("type") == "citations" and payload.get("citations"):
                    citations = _normalize_citations(payload.get("citations"))

                delta = (
                    payload.get("textDelta")
                    or payload.get("text_delta")
                    or (payload.get("type") == "text-delta" and payload.get("textDelta"))
                )
                if delta:
                    answer_parts.append(str(delta))

                # Legacy / flat citation keys
                if payload.get("citations") and payload.get("type") != "citations":
                    citations = _normalize_citations(payload.get("citations"))

        if error_message and not answer_parts and not structured_edits:
            raise RuntimeError(error_message)

        answer = "".join(answer_parts).strip()
        answer = re.sub(r"```[\s\S]*?```", "", answer, flags=re.DOTALL).strip()

        structured_edits = _attach_selection_to_edits(
            structured_edits,
            selected_text=selected_text,
            selection_range=selection_range,
        )

        if structured_edits and not answer:
            answer = f"Предлагаю {len(structured_edits)} правку(-и). Примите или отклоните каждую."
        if editor_mode_hint == "draft" and answer and not structured_edits:
            # Draft: answer is the snippet to insert
            pass
        elif not answer:
            answer = "Не удалось получить ответ. Попробуйте переформулировать запрос."

        if structured_edits:
            suggestions.append("Применить все правки")

        return {
            "answer": answer,
            "citations": citations,
            "suggestions": suggestions,
            "edited_content": edited_content,
            "structured_edits": structured_edits,
        }
