"""
Editor chat turn contract — product model for Ask / Edit / Draft.

Each user message is one Turn with a stable turn_id, explicit intent, and
ephemeral graph fields reset at turn start (not leftover checkpoint artifacts).
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

EditorTurnIntent = Literal["ask", "edit", "draft"]

# LangGraph nodes that may *produce* patch proposals for the UI (not passthrough nodes).
EDITOR_PATCH_EMIT_NODES = frozenset(
    {
        "generate_edits",
        "generate_editor_snippet",
    }
)

# Nodes that emit the final assistant message for editor chat (without generate_response LLM).
EDITOR_FINAL_RESPONSE_NODES = frozenset(
    {
        "generate_response",
        "apply_edits",
        "generate_editor_snippet",
    }
)


def normalize_editor_intent(editor_mode_hint: Optional[str]) -> EditorTurnIntent:
    raw = (editor_mode_hint or "ask").strip().lower()
    if raw in ("ask", "edit", "draft"):
        return raw  # type: ignore[return-value]
    return "ask"


def reset_editor_ephemeral_for_turn(
    state: Dict[str, Any],
    *,
    turn_id: str,
    intent: EditorTurnIntent,
) -> None:
    """
    Clear execution-scoped editor artifacts before graph.astream.

    Long-term dialog lives in ``messages``; patch sets and answers must not
    leak across turns via checkpoint merge.
    """
    state["active_turn_id"] = turn_id
    state["turn_intent"] = intent

    state["structured_edits"] = None
    state["waiting_for_edits_approval"] = False
    state["edits_approved"] = False
    state["edited_content"] = None
    state["edits_valid"] = None
    state["edit_errors"] = None
    state["edit_validation_iteration"] = None
    state["edit_iterations"] = None
    state["improved_text"] = None
    state["document_analysis"] = None
    state["risks"] = None

    # Answer / retrieval for the new question only (also set in ChatGraphService).
    state["response"] = None
    state["rag_context"] = None
    state["garant_context"] = None
    state["rag_documents"] = None
    state["citations"] = None
    state["context_pipeline_meta"] = None
    state["answer_blocks"] = None


def should_emit_patch_proposals(
    *,
    intent: EditorTurnIntent,
    graph_node: str,
    structured_edits: Any,
) -> bool:
    if intent != "edit":
        return False
    if graph_node not in EDITOR_PATCH_EMIT_NODES:
        return False
    if not structured_edits or not isinstance(structured_edits, list):
        return False
    return len(structured_edits) > 0
