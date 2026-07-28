"""Entity token grounding for statement filters (shared by toolkit + turn contract)."""
from __future__ import annotations

import re
from typing import Any, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_plan_validate import extract_content_tokens
from app.services.chat.statement_sql_value_grounding import (
    DbDescriptionMatchProbe,
    RowsDescriptionMatchProbe,
)

_FIO_RE = re.compile(
    r"\b[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?\s+[А-ЯЁ]\.[А-ЯЁ]\."
)
_ORG_RE = re.compile(
    r"\b(?:ООО|АО|ПАО|ИП|ЗАО|НАО)\s+\"?[А-ЯЁA-Za-z0-9][^,\n\"]{2,80}\"?",
    re.IGNORECASE,
)


def stem_probe_variants(token: str) -> List[str]:
    raw = (token or "").strip()
    if not raw:
        return []
    out = [raw]
    if len(raw) >= 6 and re.match(r"^[А-ЯЁа-яё]", raw):
        for cut in (1, 2):
            stem = raw[:-cut]
            if len(stem) >= 4:
                out.append(stem)
    return out


def entity_needle_candidates(question: str) -> List[str]:
    q = (question or "").strip()
    out: List[str] = []
    seen: set[str] = set()

    def _add(item: str) -> None:
        for variant in stem_probe_variants(item):
            text = (variant or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)

    for m in _FIO_RE.findall(q):
        _add(m)
        parts = m.split()
        if parts:
            _add(parts[0])
    for m in _ORG_RE.findall(q):
        _add(m.strip())
    for token in extract_content_tokens(q):
        _add(token)
    return out


def ground_counterparty_needle(
    question: str,
    *,
    rows: Optional[Sequence[CaseFileTransaction]] = None,
    db: Optional[Session] = None,
    case_id: str = "",
    file_id: str = "",
) -> str:
    """Prefer specific surname/org anchors over high-hit short prefixes."""
    return select_best_entity_token(
        question,
        rows=rows,
        db=db,
        case_id=case_id,
        file_id=file_id,
    )


def _is_patronymic_anchor(token: str) -> bool:
    return bool(re.search(r"(ович|евич)", token or "", re.IGNORECASE))


def _person_surname_anchors(question: str) -> List[str]:
    """Content anchors for person/org lookup; surnames before patronymics."""
    tokens = extract_content_tokens(question or "")
    anchors = [t for t in tokens if len(t) >= 5 and re.search(r"[А-Яа-яA-Za-z]", t)]
    anchors.sort(key=lambda t: (_is_patronymic_anchor(t), -len(t)))
    return anchors


def _anchor_probe_hits(probe: Any, anchor: str) -> tuple[int, str]:
    """Best hit count and token variant for an anchor (handles Russian case endings)."""
    best_hits = 0
    best_token = ""
    head = (anchor or "").strip().split()[0] if anchor else ""
    for seed in (head, anchor):
        if not seed:
            continue
        for variant in stem_probe_variants(seed):
            hits = probe.count(variant)
            if hits > best_hits or (hits == best_hits and len(variant) > len(best_token)):
                best_hits = hits
                best_token = variant
    return best_hits, best_token


def select_best_entity_token(
    question: str,
    *,
    rows: Optional[Sequence[CaseFileTransaction]] = None,
    db: Optional[Session] = None,
    case_id: str = "",
    file_id: str = "",
) -> str:
    """
    Choose a description filter token for person/org questions.

    Specificity beats raw hit count (avoids «Андре» when «Андропов» exists).
    """
    candidates = entity_needle_candidates(question)
    if not candidates:
        return ""

    if rows is not None:
        probe = RowsDescriptionMatchProbe(rows=rows)
    elif db is not None and case_id and file_id:
        probe = DbDescriptionMatchProbe(db=db, case_id=case_id, file_id=file_id)
    else:
        return ""

    anchors = _person_surname_anchors(question)
    surname_heads: List[str] = []
    for anchor in anchors:
        if _is_patronymic_anchor(anchor):
            continue
        head = (anchor.split()[0] if anchor else "").strip()
        if head and head not in surname_heads:
            surname_heads.append(head)

    if surname_heads:
        primary = surname_heads[0]
        hits, token = _anchor_probe_hits(probe, primary)
        if hits > 0 and token:
            return token
        for variant in stem_probe_variants(primary):
            if len(variant) >= 5:
                return variant
        return primary

    for anchor in anchors:
        hits, token = _anchor_probe_hits(probe, anchor)
        if hits > 0 and token:
            return token

    best = ""
    best_score: tuple[int, int, int] = (-1, -1, -1)
    for raw in candidates:
        token = (raw or "").strip()
        if not token or _is_description_filter_noise(token):
            continue
        if anchors and _is_patronymic_anchor(token):
            continue
        hits = probe.count(token)
        if hits <= 0:
            continue
        score = (len(token), -min(hits, 9999), hits)
        if score > best_score:
            best_score = score
            best = token
    return best


def _is_description_filter_noise(token: str) -> bool:
    from app.services.chat.statement_sql_plan_validate import is_description_filter_noise

    return is_description_filter_noise(token)
