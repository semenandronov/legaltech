"""Resolve the issuance/signing date of THIS document (any legal doc type).

Production contract (not contract-only):
- Prefer a narrow front zone (preamble / title block), never a blind mid-body window.
- Collect date candidates; score them; never return the first dotted date blindly.
- Reject citation dates (ФЗ, ред. от, references to other instruments).
- Tolerate OCR noise («16 » апреля 2024 г.).
- If uncertain — return None (empty is better than a wrong date).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from app.services.front_matter_facts import (
    find_hard_body_section_start,
    select_front_matter_zone,
)

# Soft fallback when no hard section cut is found. Document dates almost always
# sit in the title block; keeping this short avoids swallowing body citations.
_FALLBACK_ZONE_CHARS = 550
_HARD_CUT_ZONE_CAP = 1400
_CONTEXT_PAD = 90
_MIN_ACCEPT_SCORE = 2.2
# Citation checks stay line-local so later body phrases ("в соответствии с…")
# do not poison a clean header date.
_CITATION_LEFT_PAD = 70
_CITATION_RIGHT_PAD = 45

_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

_MONTH_ALT = "|".join(_MONTHS.keys())

# OCR: «16 » апреля / «25» июля / 16 апреля 2024 г.
_RU_MONTH_DATE_RE = re.compile(
    rf"(?i)(?:от\s+)?"
    rf"[«\"„]?\s*(?P<day>\d{{1,2}})\s*[»\"“]?\s+"
    rf"(?P<month>{_MONTH_ALT})"
    rf"\s+(?P<year>20\d{{2}})\s*г?\.?"
)

_DOT_DATE_RE = re.compile(
    r"(?i)\b(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>20\d{2})\s*г?\.?\b"
)

_ISO_DATE_RE = re.compile(
    r"\b(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\b"
)

# Strong reject: date belongs to another instrument / statute, not this doc.
_CITATION_REJECT_RE = re.compile(
    r"(?i)(?:"
    r"федеральн\w*\s+закон|"
    r"закон\w*\s+от|"
    r"\b(?:фз|гк\s*рф|нк\s*рф|тк\s*рф|коап|апк|гпк)\b|"
    r"N\s*[\d\-]+\s*[-–—]?\s*ФЗ|"
    r"№\s*[\d\-]+\s*[-–—]?\s*ФЗ|"
    r"ред\.?\s*от|"
    r"в\s+редакции\s+от|"
    r"в\s+соответстви[ие]\s+с|"
    r"согласно\s+(?:ст\.|стать)"
    r")"
)

# Soft reject: date attached to a referenced other contract/document.
_REF_OTHER_DOC_RE = re.compile(
    r"(?i)(?:"
    r"к\s+договору|"
    r"к\s+соглашени|"
    r"на\s+основании\s+договор|"
    r"во\s+исполнение|"
    r"ранее\s+заключ"
    r")"
)

_TITLEISH_RE = re.compile(
    r"(?i)\b(?:"
    r"договор|соглашени|контракт|акт|решени|определени|"
    r"постановлени|выписк|письм|поручени|уведомлени|"
    r"протокол|доверенност|приказ|заявлени"
    r")\b"
)

_DOC_NUMBER_YEAR_RE = re.compile(
    r"(?i)(?:№|N[oо]?\.?)\s*[0-9A-Za-z][0-9A-Za-z/\-–—._]*?(20\d{2})"
)


@dataclass(frozen=True)
class DocumentDateHit:
    iso_date: str
    verbatim: str
    char_start: int
    char_end: int
    confidence: float
    score: float
    rationale: str


@dataclass(frozen=True)
class _Candidate:
    iso_date: str
    verbatim: str
    start: int
    end: int
    kind: str  # ru_month | dot | iso


def select_document_date_zone(text: str) -> Tuple[str, int]:
    """
    Narrow front zone for issuance-date search.

    Prefer cut before the first hard body section; otherwise a short title-block
    fallback (~550 chars). Never opens a multi-page window by default.
    """
    body = text or ""
    if not body.strip():
        return "", 0

    hard_at = find_hard_body_section_start(body)
    if hard_at is not None:
        zone, end = select_front_matter_zone(
            body,
            max_chars=min(_HARD_CUT_ZONE_CAP, max(hard_at + 80, _FALLBACK_ZONE_CHARS)),
        )
        return zone, end

    end = min(len(body), _FALLBACK_ZONE_CHARS)
    nl = body.rfind("\n\n", max(0, end - 200), end)
    if nl > end // 3:
        end = nl
    return body[:end], end


def _safe_iso(year: int, month: int, day: int) -> Optional[str]:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _context_window(text: str, start: int, end: int, pad: int = _CONTEXT_PAD) -> str:
    lo = max(0, start - pad)
    hi = min(len(text), end + pad)
    return text[lo:hi]


def _citation_context(text: str, start: int, end: int) -> str:
    """Prefer the date's own line(s); avoid swallowing following paragraphs."""
    line_lo = text.rfind("\n", 0, start) + 1
    line_hi = text.find("\n", end)
    if line_hi < 0:
        line_hi = len(text)
    lo = max(0, min(line_lo, start - _CITATION_LEFT_PAD))
    hi = min(len(text), max(line_hi, end + _CITATION_RIGHT_PAD))
    # Do not cross more than one extra newline after the date line.
    nxt = text.find("\n\n", end)
    if nxt >= 0:
        hi = min(hi, nxt)
    return text[lo:hi]


def _year_hints(text: str, filename: str) -> Tuple[int, ...]:
    years: List[int] = []
    for src in (filename or "", text[:800]):
        for m in _DOC_NUMBER_YEAR_RE.finditer(src):
            try:
                years.append(int(m.group(1)))
            except ValueError:
                pass
        for m in re.finditer(r"(20\d{2})", src):
            # Filename years only when not part of a long digit run noise.
            if src is filename or m.start() < 400:
                try:
                    y = int(m.group(1))
                    if 2000 <= y <= 2099:
                        years.append(y)
                except ValueError:
                    pass
    # Preserve order, unique.
    return tuple(dict.fromkeys(years))


def _iter_candidates(zone: str, *, abs_offset: int = 0) -> List[_Candidate]:
    out: List[_Candidate] = []
    if not zone:
        return out

    for m in _RU_MONTH_DATE_RE.finditer(zone):
        month = _MONTHS.get(m.group("month").lower())
        if not month:
            continue
        iso = _safe_iso(int(m.group("year")), month, int(m.group("day")))
        if not iso:
            continue
        out.append(
            _Candidate(
                iso_date=iso,
                verbatim=m.group(0).strip(),
                start=abs_offset + m.start(),
                end=abs_offset + m.end(),
                kind="ru_month",
            )
        )

    for m in _DOT_DATE_RE.finditer(zone):
        iso = _safe_iso(int(m.group("year")), int(m.group("month")), int(m.group("day")))
        if not iso:
            continue
        out.append(
            _Candidate(
                iso_date=iso,
                verbatim=m.group(0).strip(),
                start=abs_offset + m.start(),
                end=abs_offset + m.end(),
                kind="dot",
            )
        )

    for m in _ISO_DATE_RE.finditer(zone):
        iso = _safe_iso(int(m.group("year")), int(m.group("month")), int(m.group("day")))
        if not iso:
            continue
        out.append(
            _Candidate(
                iso_date=iso,
                verbatim=m.group(0).strip(),
                start=abs_offset + m.start(),
                end=abs_offset + m.end(),
                kind="iso",
            )
        )

    # De-dupe identical spans.
    uniq: dict[Tuple[int, int, str], _Candidate] = {}
    for c in out:
        uniq[(c.start, c.end, c.iso_date)] = c
    return list(uniq.values())


def _score_candidate(
    cand: _Candidate,
    *,
    full_text: str,
    zone_len: int,
    year_hints: Sequence[int],
) -> Tuple[float, str]:
    cite_ctx = _citation_context(full_text, cand.start, cand.end)
    soft_ctx = _context_window(full_text, cand.start, cand.end)
    reasons: List[str] = []

    if _CITATION_REJECT_RE.search(cite_ctx):
        return -100.0, "citation_or_statute_context"

    score = 1.0

    # Earlier in the document is strongly preferred.
    if cand.start <= 120:
        score += 3.0
        reasons.append("very_early")
    elif cand.start <= 350:
        score += 2.2
        reasons.append("early")
    elif cand.start <= 700:
        score += 1.2
        reasons.append("upper_block")
    else:
        score -= 0.4
        reasons.append("late_in_zone")

    if cand.kind == "ru_month":
        score += 2.4
        reasons.append("ru_month_form")
    elif cand.kind == "dot":
        score += 0.6
        reasons.append("dot_form")
    else:
        score += 0.4
        reasons.append("iso_form")

    # Guillemet day («16») is a classic RU issuance marker.
    if re.search(r"[«\"„]\s*\d{1,2}\s*[»\"“]", cand.verbatim):
        score += 1.2
        reasons.append("guillemet_day")

    pre = full_text[max(0, cand.start - 220) : cand.start]
    if _TITLEISH_RE.search(pre):
        score += 1.3
        reasons.append("near_title")

    if _REF_OTHER_DOC_RE.search(soft_ctx):
        score -= 4.0
        reasons.append("other_doc_reference")

    y = int(cand.iso_date[:4])
    if year_hints and y in year_hints[:4]:
        score += 1.1
        reasons.append("year_matches_number")
    elif year_hints and all(abs(y - h) >= 3 for h in year_hints[:3]):
        score -= 1.5
        reasons.append("year_mismatch")

    # Dotted dates deep after parties/body language are weak issuance signals.
    if cand.kind == "dot" and cand.start > min(450, max(200, zone_len // 2)):
        score -= 1.2
        reasons.append("late_dot_date")

    return score, ",".join(reasons) if reasons else "base"


def resolve_document_issuance_date(
    text: str,
    *,
    filename: str = "",
    min_score: float = _MIN_ACCEPT_SCORE,
) -> Optional[DocumentDateHit]:
    """
    Best-effort issuance/signing date for the document represented by ``text``.

    Returns None when no candidate clears the quality bar (prefer empty over wrong).
    """
    body = text or ""
    if not body.strip():
        return None

    zone, _zone_end = select_document_date_zone(body)
    if not zone.strip():
        return None

    # Candidates are matched on the zone; offsets are absolute in ``body``.
    candidates = _iter_candidates(zone, abs_offset=0)
    if not candidates:
        # Rare: hard cut too early (date after a false section). Peek a bit more,
        # still well below the old 2500-char trap.
        extended = body[: min(len(body), max(_FALLBACK_ZONE_CHARS, 900))]
        if extended != zone:
            candidates = _iter_candidates(extended, abs_offset=0)
            zone = extended
    if not candidates:
        return None

    year_hints = _year_hints(zone, filename)
    scored: List[Tuple[float, str, _Candidate]] = []
    for cand in candidates:
        sc, why = _score_candidate(
            cand,
            full_text=body,
            zone_len=len(zone),
            year_hints=year_hints,
        )
        scored.append((sc, why, cand))

    scored.sort(key=lambda x: (-x[0], x[2].start))
    best_score, best_why, best = scored[0]
    if best_score < min_score:
        return None

    # Confidence saturates with score margin over the acceptance floor.
    conf = min(0.96, 0.62 + 0.06 * (best_score - min_score))
    if best.kind == "ru_month" and best.start <= 400:
        conf = max(conf, 0.88)

    return DocumentDateHit(
        iso_date=best.iso_date,
        verbatim=best.verbatim,
        char_start=best.start,
        char_end=best.end,
        confidence=round(conf, 3),
        score=round(best_score, 3),
        rationale=best_why,
    )
