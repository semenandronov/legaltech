"""
Evidence scope — file scope derived from turn contract + session anchors.

Uses prior-turn citation file_ids and catalog metadata overlap — not ad-hoc
filename regex or per-question router patches.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from app.services.chat.retrieval_router import CaseFileCatalogEntry, RetrievalTask

_SCOPED_INTENTS = frozenset(
    {"drill_down", "narrow_fact", "standard_case_qa", "legal_analysis", "cross_doc_analysis"}
)


@dataclass(frozen=True)
class EvidenceScope:
    """Resolved file scope for one turn (immutable)."""

    file_ids: tuple[str, ...]
    scope_mode: str
    confidence: float
    reason: str

    def to_retrieval_task(self, question: str) -> RetrievalTask:
        q = (question or "").strip()
        return RetrievalTask(
            search_query=q,
            file_ids=list(self.file_ids),
            scope_mode=self.scope_mode,  # type: ignore[arg-type]
            confidence=self.confidence,
            rationale=f"evidence_scope_{self.reason}",
            within_file_expand=bool(self.file_ids),
        )


def _question_tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-zа-яё0-9]{4,}", (text or "").lower()) if t]


def _score_catalog_entry(entry: CaseFileCatalogEntry, question: str) -> float:
    tokens = _question_tokens(question)
    if not tokens:
        return 0.0
    blob = " ".join(
        [
            entry.filename or "",
            entry.summary or "",
            " ".join(entry.key_points or []),
        ]
    ).lower()
    if not blob.strip():
        return 0.0
    hits = sum(1 for t in tokens if t in blob)
    return hits / len(tokens)


def resolve_evidence_scope(
    *,
    primary_intent: str,
    question: str,
    anchor_file_ids: Sequence[str],
    catalog: Sequence[CaseFileCatalogEntry],
    inherited_file_ids: Sequence[str] = (),
    min_score: float = 0.22,
    min_gap: float = 0.10,
) -> Optional[EvidenceScope]:
    """
    Narrow retrieval to session-anchored file(s) when intent requires scoped read.

    Mandatory inheritance: when inherited_file_ids are set (referential follow-up),
    skip catalog scoring and use citation scope directly.
    """
    inherited = tuple(str(x).strip() for x in inherited_file_ids if str(x).strip())
    if inherited:
        return EvidenceScope(
            file_ids=inherited,
            scope_mode="resolved",
            confidence=0.95,
            reason="turn_context_mandatory_inheritance",
        )

    intent = (primary_intent or "").strip().lower()
    if intent not in _SCOPED_INTENTS:
        return None

    q = (question or "").strip()
    if not q or not catalog:
        return None

    anchor_set = {str(x).strip() for x in anchor_file_ids if str(x).strip()}
    entries = [e for e in catalog if e.file_id in anchor_set] if anchor_set else list(catalog)
    if not entries:
        return None

    scored = sorted(
        ((_score_catalog_entry(e, q), e.file_id) for e in entries),
        key=lambda x: x[0],
        reverse=True,
    )
    top_score, top_id = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    if top_score < min_score:
        return None

    clear_winner = len(scored) == 1 or (top_score - second_score) >= min_gap
    narrow_anchor = anchor_set and len(anchor_set) <= 3

    if clear_winner or (narrow_anchor and top_score >= min_score):
        conf = min(0.95, 0.68 + top_score * 0.32)
        reason = "session_anchor_catalog_match" if anchor_set else "catalog_question_match"
        return EvidenceScope(
            file_ids=(top_id,),
            scope_mode="resolved",
            confidence=conf,
            reason=reason,
        )

    return None
