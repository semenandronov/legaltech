"""
SSE turn emitter — single protocol surface for document editor chat streams.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.services.chat.events import SSESerializer
from app.services.chat.turn_contract import (
    EditorTurnIntent,
    normalize_editor_intent,
    should_emit_patch_proposals,
)


class EditorTurnEmitter:
    """Emits turn-scoped SSE; filters stale checkpoint artifacts."""

    def __init__(
        self,
        *,
        turn_id: str,
        intent: EditorTurnIntent,
        document_id: Optional[str] = None,
    ) -> None:
        self.turn_id = turn_id
        self.intent = intent
        self.document_id = document_id
        self._patches_emitted = False
        self.last_patch_count = 0

    @classmethod
    def for_editor(
        cls,
        turn_id: str,
        editor_mode_hint: Optional[str],
        document_id: Optional[str] = None,
    ) -> "EditorTurnEmitter":
        return cls(
            turn_id=turn_id,
            intent=normalize_editor_intent(editor_mode_hint),
            document_id=document_id,
        )

    def _envelope(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(payload)
        out["turn_id"] = self.turn_id
        out["intent"] = self.intent
        if self.document_id:
            out["document_id"] = self.document_id
        return out

    def turn_started(self) -> str:
        return (
            "data: "
            + json.dumps(
                self._envelope({"type": "turn_started", "status": "running"}),
                ensure_ascii=False,
            )
            + "\n\n"
        )

    def turn_completed(
        self,
        *,
        answer: str,
        citations_count: int = 0,
        structured_edits_count: int = 0,
        status: str = "success",
    ) -> str:
        return (
            "data: "
            + json.dumps(
                self._envelope(
                    {
                        "type": "turn_completed",
                        "status": status,
                        "artifact_type": self._artifact_type(),
                        "answer_chars": len(answer or ""),
                        "citations_count": citations_count,
                        "structured_edits_count": structured_edits_count,
                    }
                ),
                ensure_ascii=False,
            )
            + "\n\n"
        )

    def _artifact_type(self) -> str:
        if self.intent == "edit":
            return "patch_set"
        if self.intent == "draft":
            return "draft"
        return "answer"

    def text_delta(self, text: str) -> str:
        if not text:
            return ""
        return (
            "data: "
            + json.dumps(
                self._envelope({"type": "text-delta", "textDelta": text}),
                ensure_ascii=False,
            )
            + "\n\n"
        )

    def content_sync(self, content: str) -> str:
        return (
            "data: "
            + json.dumps(
                self._envelope({"type": "content_sync", "content": content}),
                ensure_ascii=False,
            )
            + "\n\n"
        )

    def citations(self, citations: List[Dict[str, Any]]) -> str:
        body = self._envelope({"type": "citations", "citations": citations})
        return f"data: {json.dumps(body, ensure_ascii=False, default=str)}\n\n"

    def structured_edits_from_node(
        self,
        graph_node: str,
        edits: Any,
    ) -> Optional[str]:
        if not should_emit_patch_proposals(
            intent=self.intent,
            graph_node=graph_node,
            structured_edits=edits,
        ):
            return None
        self._patches_emitted = True
        self.last_patch_count = len(edits)
        raw = SSESerializer.structured_edits(edits)
        if not raw:
            return None
        # Inject turn_id into legacy payload (structured_edits key preserved for UI).
        try:
            line = raw.strip()
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                payload.update(self._envelope({}))
                return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            pass
        return raw

    def use_custom_stream_channel(self) -> bool:
        """Ask uses messages-only streaming to avoid duplicate text with custom writer."""
        return self.intent == "edit"
