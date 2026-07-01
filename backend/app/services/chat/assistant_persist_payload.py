"""
Canonical assistant message persistence payload (content + evidence).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.chat.evidence_bundle import build_evidence_bundle


def build_case_assistant_evidence(
    *,
    citations: Optional[List[Dict[str, Any]]] = None,
    turn_state: Optional[Dict[str, Any]] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = dict(extra_metadata or {})
    if isinstance(turn_state, dict) and turn_state.get("domain") not in (None, "", "none"):
        meta["turn_state"] = turn_state
    return build_evidence_bundle(
        citations=list(citations or []),
        retrieval_metadata=meta or None,
    )
