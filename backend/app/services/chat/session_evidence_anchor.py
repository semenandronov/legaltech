"""
Evidence-anchored replay: prior assistant turn + citations, optionally sliced by semantic focus.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence, Tuple

from app.services.chat.evidence_bundle import evidence_citations
from app.services.chat.session_evidence_resolution import SessionEvidenceReply
from app.services.court_practice_text import extract_case_numbers


def _score_block(block: str, focus: str, case_numbers: Sequence[str]) -> float:
    text = (block or "").lower()
    if not text:
        return 0.0
    score = 0.0
    focus_l = (focus or "").lower()
    if focus_l:
        for token in re.findall(r"[а-яёa-z0-9]{4,}", focus_l):
            if token in text:
                score += 1.0
    for cn in case_numbers:
        if cn.lower() in text:
            score += 3.0
    return score


def slice_assistant_content(
    content: str,
    *,
    focus: str = "",
    case_numbers: Sequence[str] = (),
) -> str:
    """
    Pick the most relevant slice of a long assistant answer (no phrase triggers).
    """
    body = (content or "").strip()
    if not body:
        return body
    if not (focus or "").strip() and not case_numbers:
        return body

    blocks = re.split(r"\n(?=##\s|\*\*|(?:\d+[\.\)]\s))", body)
    if len(blocks) <= 1:
        blocks = re.split(r"\n{2,}", body)

    scored: List[Tuple[float, str]] = []
    for b in blocks:
        b_st = b.strip()
        if not b_st:
            continue
        scored.append((_score_block(b_st, focus, case_numbers), b_st))

    if not scored:
        return body

    scored.sort(key=lambda x: x[0], reverse=True)
    if scored[0][0] <= 0:
        return body

    top_blocks = [scored[0][1]]
    for sc, blk in scored[1:3]:
        if sc >= scored[0][0] * 0.6 and sc > 0:
            top_blocks.append(blk)
    return "\n\n".join(top_blocks) if len(top_blocks) < len(blocks) else body


def filter_citations_for_focus(
    citations: List[dict],
    *,
    focus: str = "",
    case_numbers: Sequence[str] = (),
) -> List[dict]:
    if not citations:
        return []
    targets = {c.upper() for c in case_numbers if c}
    if not targets and not (focus or "").strip():
        return citations

    filtered: List[dict] = []
    for c in citations:
        cit_text = " ".join(
            str(c.get(k) or "")
            for k in ("quote", "file_name", "text", "case_number")
        )
        cit_cases = {x.upper() for x in extract_case_numbers(cit_text)}
        if targets and cit_cases & targets:
            filtered.append(c)
            continue
        if focus and _score_block(cit_text, focus, ()) > 0:
            filtered.append(c)
    return filtered or citations


def build_evidence_anchor_reply(
    *,
    message_id: str,
    content: str,
    evidence: Any,
    focus: str = "",
    resolution_kind: str = "semantic_anchor",
) -> SessionEvidenceReply:
    case_numbers = tuple(extract_case_numbers(content or ""))
    if focus:
        case_numbers = tuple(
            dict.fromkeys(list(case_numbers) + list(extract_case_numbers(focus)))
        )

    sliced = slice_assistant_content(content, focus=focus, case_numbers=case_numbers)
    cits = evidence_citations(evidence)
    cits = filter_citations_for_focus(cits, focus=focus, case_numbers=case_numbers)

    return SessionEvidenceReply(
        content=sliced,
        citations=cits,
        resolution_kind=resolution_kind,
        message_id=message_id,
        matched_case_numbers=case_numbers,
    )


def find_turn_by_id(turns: Sequence, message_id: str):
    mid = (message_id or "").strip()
    if not mid:
        return None
    for t in turns:
        if t.message_id == mid:
            return t
    return None
