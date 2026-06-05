from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.chat.court_practice_answer_contract import extract_case_numbers_from_citations


def build_evidence_bundle(
    *,
    citations: Optional[List[Dict[str, Any]]] = None,
    retrieval_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Canonical evidence bundle persisted alongside assistant messages.

    Contract:
    - citations: list[dict] compatible with SSE "citations" payload.
    - case_numbers: derived from citations (court_practice only).
    - retrieval_metadata: best-effort debugging/observability payload.
    """
    cits = list(citations or [])
    case_numbers = extract_case_numbers_from_citations(cits)
    out: Dict[str, Any] = {
        "citations": cits,
        "case_numbers": case_numbers,
    }
    if retrieval_metadata:
        out["retrieval_metadata"] = retrieval_metadata
    return out


def evidence_citations(evidence: Any) -> List[Dict[str, Any]]:
    """
    Best-effort reader for evidence bundle citations.
    Supports both canonical shape {"citations":[...]} and legacy direct list.
    """
    if not evidence:
        return []
    if isinstance(evidence, list):
        return [c for c in evidence if isinstance(c, dict)]
    if isinstance(evidence, dict):
        cits = evidence.get("citations") or []
        if isinstance(cits, list):
            return [c for c in cits if isinstance(c, dict)]
    return []

