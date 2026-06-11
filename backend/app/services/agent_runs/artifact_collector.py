"""Collect structured workflow artifacts from tool outputs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def artifact_from_tool_result(tool: str, output: Dict[str, Any], *, case_id: str) -> Optional[Dict[str, Any]]:
    """Map successful tool output to a UI-friendly artifact record."""
    if not isinstance(output, dict):
        return None

    if tool == "agent_draft" and output.get("document_id"):
        doc_id = str(output["document_id"])
        title = str(output.get("title") or "Черновик документа")
        path = str(output.get("editor_path") or f"/cases/{case_id}/editor/{doc_id}")
        return {
            "type": "document",
            "id": doc_id,
            "title": title,
            "path": path,
            "preview": str(output.get("preview") or "")[:500],
            "tool": tool,
        }

    if tool == "agent_tabular_review" and output.get("review_id"):
        review_id = str(output["review_id"])
        title = str(output.get("review_name") or "Таблица")
        return {
            "type": "tabular_review",
            "id": review_id,
            "title": title,
            "path": f"/cases/{case_id}/tabular-review/{review_id}",
            "row_count": len(output.get("rows") or []),
            "saved_count": int(output.get("saved_count") or 0),
            "tool": tool,
        }

    return None


def merge_artifact_items(
    existing: Optional[Dict[str, Any]],
    new_item: Dict[str, Any],
) -> Dict[str, Any]:
    """Append artifact; dedupe by type+id."""
    items: List[Dict[str, Any]] = list((existing or {}).get("items") or [])
    key = (new_item.get("type"), new_item.get("id"))
    if any((it.get("type"), it.get("id")) == key for it in items):
        return {"items": items}
    items.append(new_item)
    return {"items": items}
