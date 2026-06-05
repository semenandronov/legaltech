"""Structured evidence from the prior assistant turn (Turn Context Contract)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from app.services.chat.evidence_bundle import evidence_citations
from app.services.chat.session_context_types import SessionMessageTurn


@dataclass(frozen=True)
class CitationAnchor:
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_excerpt: str = ""
    citation_index: int | None = None


@dataclass(frozen=True)
class PriorTurnEvidence:
    message_id: str
    assistant_excerpt: str
    citations: tuple[CitationAnchor, ...]
    retrieval_metadata: dict


def _anchor_from_citation(citation: dict, index: int) -> Optional[CitationAnchor]:
    if not isinstance(citation, dict):
        return None
    source_id = str(citation.get("source_id") or citation.get("file_id") or "").strip()
    if not source_id or source_id == "unknown":
        return None
    chunk_id = citation.get("chunk_id")
    char_start = citation.get("char_start")
    char_end = citation.get("char_end")
    quote = str(citation.get("quote") or citation.get("text") or "")[:500]
    return CitationAnchor(
        source_id=source_id,
        chunk_id=str(chunk_id).strip() if chunk_id else None,
        char_start=int(char_start) if char_start is not None else None,
        char_end=int(char_end) if char_end is not None else None,
        quote_excerpt=quote,
        citation_index=index,
    )


def load_prior_turn_evidence_from_turns(
    turns: Sequence[SessionMessageTurn],
    *,
    exclude_message_ids: Optional[Sequence[str]] = None,
) -> Optional[PriorTurnEvidence]:
    """Most recent assistant turn with persisted content (citations optional)."""
    excluded = {str(x).strip() for x in (exclude_message_ids or []) if str(x).strip()}
    for turn in reversed(list(turns)):
        if (turn.role or "").lower() != "assistant":
            continue
        if turn.message_id in excluded:
            continue
        body = (turn.content or "").strip()
        if not body:
            continue

        citations_raw = evidence_citations(turn.evidence)
        anchors: List[CitationAnchor] = []
        for idx, cit in enumerate(citations_raw):
            anchor = _anchor_from_citation(cit, idx)
            if anchor is not None:
                anchors.append(anchor)

        retrieval_meta: Dict[str, Any] = {}
        if isinstance(turn.evidence, dict):
            raw_meta = turn.evidence.get("retrieval_metadata")
            if isinstance(raw_meta, dict):
                retrieval_meta = dict(raw_meta)

        return PriorTurnEvidence(
            message_id=turn.message_id,
            assistant_excerpt=body[:2500],
            citations=tuple(anchors),
            retrieval_metadata=retrieval_meta,
        )
    return None


def unique_inherited_file_ids(prior: PriorTurnEvidence) -> tuple[str, ...]:
    """Citation source_ids from prior turn — mandatory scope for referential follow-ups."""
    seen: set[str] = set()
    ordered: List[str] = []
    for anchor in prior.citations:
        fid = (anchor.source_id or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            ordered.append(fid)
    if ordered:
        return tuple(ordered)

    raw_ids = prior.retrieval_metadata.get("file_ids") or prior.retrieval_metadata.get(
        "scoped_file_ids"
    )
    if isinstance(raw_ids, list):
        for item in raw_ids:
            fid = str(item).strip()
            if fid and fid not in seen:
                seen.add(fid)
                ordered.append(fid)
    return tuple(ordered)


def anchor_chunk_ids(prior: PriorTurnEvidence) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for anchor in prior.citations:
        cid = (anchor.chunk_id or "").strip()
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return tuple(out)
