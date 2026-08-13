"""In-document cross-reference parse + resolve (production).

Supports RU/EN contract refs inside the same file:
- clauses / sections: п. 5.1, пункт 10.2, Section 8.2
- appendices: Приложение №1, Appendix A, Schedule 2
- nested: п. 2 Приложения №1

Reliability contract:
- Prefer precise hits over broad prefix guesses.
- Never follow external statute citations (ФЗ, ред. от …).
- Ambiguous clause numbers that exist in both body and appendix → body only
  unless the ref explicitly names an appendix.
- Empty / ambiguous resolve → no follow (caller keeps hybrid retrieval).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

RefKind = str  # clause | appendix | appendix_clause | quote | external


@dataclass(frozen=True)
class ContractRefTarget:
    kind: RefKind
    anchor: str
    raw: str
    appendix_no: str = ""
    clause_path: str = ""
    confidence: float = 1.0

    @property
    def normalized_key(self) -> Tuple[str, str, str, str]:
        return (self.kind, self.appendix_no, self.clause_path or self.anchor, self.raw.lower())


@dataclass(frozen=True)
class OutlineAnchorRow:
    section_root_id: str
    section_number: str
    section_title: str
    section_label: str
    section_kind: str = "body"  # body | appendix | appendix_part
    appendix_no: str = ""
    char_start: int = 0
    char_end: int = 0


# ---------------------------------------------------------------------------
# Regex library
# ---------------------------------------------------------------------------

_APPENDIX_HEADING_RE = re.compile(
    r"(?i)\b(?:"
    r"приложени[еюя]|спецификаци[яи]|appendix|exhibit|schedule|annex"
    r")\s*(?:№|N[oо]?\.?|#)?\s*"
    r"(?P<no>[0-9]+|[IVXLCDM]+|[A-Za-zА-Яа-я])\b"
)

_APPENDIX_REF_RE = re.compile(
    r"(?i)\b(?:"
    r"приложени[еюя]|спецификаци[яи]|appendix|exhibit|schedule|annex"
    r")\s*(?:№|N[oо]?\.?|#)?\s*"
    r"(?P<no>[0-9]+|[IVXLCDM]+|[A-Za-zА-Яа-я])\b"
)

# п. 2 Приложения №1  /  пункт 3 приложения 2
# Note: plain «п.» must be an explicit alternative — «п\.?\s*п\.?» alone
# requires two «п» and misses the common «п. 2 Приложения №1» form.
_CLAUSE_IN_APPENDIX_RE = re.compile(
    r"(?i)\b(?:пп\.?|п\.?\s*п\.?|пункт(?:а|ом|ы|ах|у)?|подпункт(?:а|ом|ы)?|п\.)\s*"
    r"(?P<clause>[0-9]+(?:\.[0-9]+)*)"
    r"\s*(?:[-–—]\s*[0-9]+(?:\.[0-9]+)*)?\s*"
    r"(?:настоящего\s+)?"
    r"(?:приложени[еюя]|спецификаци[яи]|appendix|exhibit|schedule|annex)"
    r"\s*(?:№|N[oо]?\.?|#)?\s*"
    r"(?P<no>[0-9]+|[IVXLCDM]+|[A-Za-zА-Яа-я])\b"
)

# Приложение №1 (п. 2) / Приложения №3, п. 1.2
_APPENDIX_THEN_CLAUSE_RE = re.compile(
    r"(?i)\b(?:"
    r"приложени[еюя]|спецификаци[яи]|appendix|exhibit|schedule|annex"
    r")\s*(?:№|N[oо]?\.?|#)?\s*"
    r"(?P<no>[0-9]+|[IVXLCDM]+|[A-Za-zА-Яа-я])"
    r"\s*[,;:]?\s*(?:\(|\b)"
    r"(?:пп\.?|п\.?\s*п\.?|пункт(?:а|ом|ы|ах|у)?|п\.)\s*"
    r"(?P<clause>[0-9]+(?:\.[0-9]+)*)"
)

_CLAUSE_RE = re.compile(
    r"(?i)\b(?:"
    r"(?:section|article|§)\s*(?P<en>[0-9]+(?:\.[0-9]+)*)|"
    r"(?:пп\.?|п\.?\s*п\.?|пункт(?:а|ом|ы|ах|у)?|подпункт(?:а|ом|ы)?|раздел|статья|п\.)\s*"
    r"(?P<ru>[0-9]+(?:\.[0-9]+)*)"
    r")\b"
)

_CLAUSE_RANGE_RE = re.compile(
    r"(?i)\b(?:пп\.?|п\.?\s*п\.?|пункт(?:ы|ов)?)\s*"
    r"(?P<a>[0-9]+(?:\.[0-9]+)*)\s*[-–—]\s*(?P<b>[0-9]+(?:\.[0-9]+)*)\b"
)

_EXTERNAL_STATUTE_RE = re.compile(
    r"(?i)(?:"
    r"федеральн\w*\s+закон|"
    r"\b(?:фз|гк\s*рф|нк\s*рф|тк\s*рф|коап|апк|гпк)\b|"
    r"N\s*[\d\-]+\s*[-–—]?\s*ФЗ|"
    r"№\s*[\d\-]+\s*[-–—]?\s*ФЗ|"
    r"ред\.?\s*от|"
    r"в\s+редакции\s+от|"
    r"в\s+соответстви[ие]\s+с\s+(?:ст\.|стать)"
    r")"
)

_QUOTED_RE = re.compile(r'"([^"]{2,80})"|«([^»]{2,80})»')


def normalize_appendix_no(raw: str) -> str:
    text = (raw or "").strip().upper().replace("№", "").strip()
    text = re.sub(r"^[NNOО]\.?\s*", "", text, flags=re.IGNORECASE)
    # Arabic digits preferred; keep roman/letter as-is.
    if re.fullmatch(r"\d+", text):
        return str(int(text))  # 01 → 1
    return text


def normalize_clause_path(raw: str) -> str:
    return re.sub(r"[^\d.]", "", (raw or "").strip()).strip(".")


def detect_appendix_heading(title: str, label: str = "") -> Tuple[str, str]:
    """Return (section_kind, appendix_no) for an outline heading."""
    blob = f"{title or ''} {label or ''}".strip()
    if not blob:
        return "body", ""
    m = _APPENDIX_HEADING_RE.search(blob)
    if not m:
        # Bare «Приложение» without number — still an appendix container.
        if re.search(r"(?i)\b(?:приложени[еюя]|appendix|exhibit|schedule|annex)\b", blob):
            return "appendix", ""
        return "body", ""
    return "appendix", normalize_appendix_no(m.group("no"))


def annotate_outline_containers(
    rows: Sequence[OutlineAnchorRow],
) -> Tuple[OutlineAnchorRow, ...]:
    """Propagate appendix_no onto following parts until the next appendix heading."""
    out: List[OutlineAnchorRow] = []
    current_app = ""
    for row in rows:
        kind, no = detect_appendix_heading(row.section_title, row.section_label)
        if kind == "appendix":
            current_app = no or current_app
            out.append(
                replace(
                    row,
                    section_kind="appendix",
                    appendix_no=no or current_app,
                )
            )
            continue
        if current_app:
            out.append(
                replace(
                    row,
                    section_kind="appendix_part",
                    appendix_no=current_app,
                )
            )
        else:
            out.append(replace(row, section_kind="body", appendix_no=""))
    return tuple(out)


def outline_rows_from_entries(outline: Sequence[Any]) -> Tuple[OutlineAnchorRow, ...]:
    """Accept OutlineSectionEntry, legacy 4-tuples, or OutlineAnchorRow."""
    rows: List[OutlineAnchorRow] = []
    for item in outline or []:
        if isinstance(item, OutlineAnchorRow):
            rows.append(item)
            continue
        if hasattr(item, "section_root_id"):
            kind = str(getattr(item, "section_kind", "") or "").strip() or "body"
            app = str(getattr(item, "appendix_no", "") or "").strip()
            if not app and kind == "body":
                det_kind, det_no = detect_appendix_heading(
                    getattr(item, "section_title", "") or "",
                    getattr(item, "section_label", "") or "",
                )
                kind, app = det_kind, det_no
            rows.append(
                OutlineAnchorRow(
                    section_root_id=str(item.section_root_id or "").strip(),
                    section_number=str(getattr(item, "section_number", "") or "").strip(),
                    section_title=str(getattr(item, "section_title", "") or "").strip(),
                    section_label=str(getattr(item, "section_label", "") or "").strip(),
                    section_kind=kind,
                    appendix_no=normalize_appendix_no(app) if app else "",
                    char_start=int(getattr(item, "char_start", 0) or 0),
                    char_end=int(getattr(item, "char_end", 0) or 0),
                )
            )
            continue
        if isinstance(item, (tuple, list)) and len(item) >= 4:
            sid, num, title, label = item[0], item[1], item[2], item[3]
            kind, app = detect_appendix_heading(str(title or ""), str(label or ""))
            rows.append(
                OutlineAnchorRow(
                    section_root_id=str(sid or "").strip(),
                    section_number=str(num or "").strip(),
                    section_title=str(title or "").strip(),
                    section_label=str(label or "").strip(),
                    section_kind=kind,
                    appendix_no=app,
                )
            )
    return annotate_outline_containers(rows)


def _external_context(text: str, start: int, end: int) -> bool:
    lo = max(0, start - 40)
    hi = min(len(text), end + 70)
    return bool(_EXTERNAL_STATUTE_RE.search(text[lo:hi]))


def parse_contract_cross_references(text: str, *, limit: int = 12) -> List[ContractRefTarget]:
    """Extract in-document anchors; skip external statute citations."""
    body = text or ""
    found: List[ContractRefTarget] = []
    seen = set()
    covered: List[Tuple[int, int]] = []

    def _add(ref: ContractRefTarget, span: Optional[Tuple[int, int]] = None) -> bool:
        key = ref.normalized_key
        if key in seen:
            return len(found) >= limit
        seen.add(key)
        found.append(ref)
        if span is not None:
            covered.append(span)
        return len(found) >= limit

    def _covered(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in covered)

    # 1) Clause inside a named appendix (most specific).
    for m in _CLAUSE_IN_APPENDIX_RE.finditer(body):
        if _external_context(body, m.start(), m.end()):
            continue
        clause = normalize_clause_path(m.group("clause"))
        app = normalize_appendix_no(m.group("no"))
        if not clause or not app:
            continue
        if _add(
            ContractRefTarget(
                kind="appendix_clause",
                anchor=f"{app}/{clause}",
                raw=m.group(0).strip(),
                appendix_no=app,
                clause_path=clause,
                confidence=0.95,
            ),
            (m.start(), m.end()),
        ):
            return found

    for m in _APPENDIX_THEN_CLAUSE_RE.finditer(body):
        if _external_context(body, m.start(), m.end()):
            continue
        clause = normalize_clause_path(m.group("clause"))
        app = normalize_appendix_no(m.group("no"))
        if not clause or not app:
            continue
        if _add(
            ContractRefTarget(
                kind="appendix_clause",
                anchor=f"{app}/{clause}",
                raw=m.group(0).strip(),
                appendix_no=app,
                clause_path=clause,
                confidence=0.92,
            ),
            (m.start(), m.end()),
        ):
            return found

    # 2) Appendix-only refs (skip if already covered by appendix_clause span).
    for m in _APPENDIX_REF_RE.finditer(body):
        if _covered(m.start(), m.end()):
            continue
        if _external_context(body, m.start(), m.end()):
            continue
        app = normalize_appendix_no(m.group("no"))
        if not app:
            continue
        if _add(
            ContractRefTarget(
                kind="appendix",
                anchor=app,
                raw=m.group(0).strip(),
                appendix_no=app,
                confidence=0.93,
            ),
            (m.start(), m.end()),
        ):
            return found

    # 3) Clause ranges → endpoints (enough to pull the block).
    for m in _CLAUSE_RANGE_RE.finditer(body):
        if _covered(m.start(), m.end()):
            continue
        if _external_context(body, m.start(), m.end()):
            continue
        a = normalize_clause_path(m.group("a"))
        b = normalize_clause_path(m.group("b"))
        for clause in (a, b):
            if not clause:
                continue
            if _add(
                ContractRefTarget(
                    kind="clause",
                    anchor=clause,
                    raw=m.group(0).strip(),
                    clause_path=clause,
                    confidence=0.8,
                ),
                (m.start(), m.end()),
            ):
                return found

    # 4) Plain clauses / sections.
    for m in _CLAUSE_RE.finditer(body):
        if _covered(m.start(), m.end()):
            continue
        if _external_context(body, m.start(), m.end()):
            continue
        # Skip matches that are actually the «п.» inside an appendix phrase already captured.
        span = m.group(0)
        if re.search(r"(?i)приложени|appendix|exhibit|schedule|annex", span):
            continue
        # If this clause sits immediately before «Приложения №…», prefer the
        # specialized parser (already handled). Skip orphan half-match.
        tail = body[m.end() : m.end() + 48]
        if _APPENDIX_REF_RE.match(tail.lstrip()) or re.match(
            r"(?i)^\s*приложени", tail
        ):
            continue
        clause = normalize_clause_path(m.group("en") or m.group("ru") or "")
        if not clause:
            continue
        if _add(
            ContractRefTarget(
                kind="clause",
                anchor=clause,
                raw=span.strip(),
                clause_path=clause,
                confidence=0.85,
            ),
            (m.start(), m.end()),
        ):
            return found

    # 5) Quoted schedule titles (weak).
    for m in _QUOTED_RE.finditer(body):
        if _covered(m.start(), m.end()):
            continue
        quoted = (m.group(1) or m.group(2) or "").strip()
        if len(quoted) < 3:
            continue
        if _add(
            ContractRefTarget(
                kind="quote",
                anchor=quoted,
                raw=quoted,
                confidence=0.55,
            ),
            (m.start(), m.end()),
        ):
            return found

    return found


def _path_related(a: str, b: str) -> bool:
    """True when a and b are equal or one is a dotted parent/child of the other."""
    if not a or not b:
        return False
    if a == b:
        return True
    a_parts = a.split(".")
    b_parts = b.split(".")
    shorter, longer = (a_parts, b_parts) if len(a_parts) <= len(b_parts) else (b_parts, a_parts)
    return longer[: len(shorter)] == shorter


def _number_matches(clause: str, number: str, title: str, label: str) -> bool:
    clause = normalize_clause_path(clause)
    number = normalize_clause_path(number)
    if not clause:
        return False
    if number and _path_related(clause, number):
        return True
    blob = f"{title} {label}".strip()
    # Leading numbered title "2. Сведения…"
    if blob and re.match(rf"^\s*{re.escape(clause)}(?:\.|\s|$)", blob):
        return True
    return False


def _score_clause_hit(ref: ContractRefTarget, row: OutlineAnchorRow) -> float:
    score = 0.0
    if not _number_matches(
        ref.clause_path or ref.anchor,
        row.section_number,
        row.section_title,
        row.section_label,
    ):
        return -1.0
    num = normalize_clause_path(row.section_number)
    clause = normalize_clause_path(ref.clause_path or ref.anchor)
    if num == clause:
        score += 5.0
    elif num and _path_related(num, clause) and len(num.split(".")) < len(clause.split(".")):
        score += 3.5  # parent section of the clause
    elif num and _path_related(num, clause) and len(num.split(".")) > len(clause.split(".")):
        score += 2.5
    else:
        score += 1.0

    if ref.kind in ("appendix", "appendix_clause"):
        if row.appendix_no and row.appendix_no == ref.appendix_no:
            score += 4.0
        elif row.section_kind == "body":
            score -= 8.0
    else:
        # Plain clause: prefer body over appendix parts with same number.
        if row.section_kind == "body":
            score += 3.0
        elif row.section_kind in ("appendix", "appendix_part"):
            score -= 2.5
    return score


def resolve_ref_to_section_root_ids(
    ref: ContractRefTarget,
    outline: Sequence[Any],
    *,
    max_hits: int = 3,
) -> Tuple[str, ...]:
    """
    Map a parsed ref onto outline section_root_ids.

    ``outline`` may be OutlineSectionEntry objects, OutlineAnchorRow, or legacy
    (section_root_id, number, title, label) tuples.
    """
    if ref.kind == "external":
        return ()

    rows = outline_rows_from_entries(outline)
    if not rows:
        return ()

    if ref.kind == "appendix":
        hits: List[str] = []
        for row in rows:
            if row.section_kind == "appendix" and row.appendix_no == ref.appendix_no:
                hits.append(row.section_root_id)
            elif (
                row.section_kind == "appendix"
                and not row.appendix_no
                and ref.appendix_no
                and ref.appendix_no in f"{row.section_title} {row.section_label}"
            ):
                hits.append(row.section_root_id)
        return tuple(dict.fromkeys(hits))[:max_hits]

    if ref.kind == "appendix_clause":
        scored: List[Tuple[float, str]] = []
        for row in rows:
            if row.appendix_no != ref.appendix_no and row.section_kind != "appendix":
                # Allow appendix heading itself only as weak fallback.
                continue
            if row.appendix_no and row.appendix_no != ref.appendix_no:
                continue
            sc = _score_clause_hit(ref, row)
            if sc < 0:
                # Appendix heading with matching number still useful as container.
                if row.section_kind == "appendix" and row.appendix_no == ref.appendix_no:
                    scored.append((1.5, row.section_root_id))
                continue
            scored.append((sc, row.section_root_id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        # If only the appendix container matched, still return it.
        return tuple(dict.fromkeys(sid for _, sid in scored[:max_hits]))

    if ref.kind == "quote":
        hits = []
        needle = (ref.anchor or "").lower()
        for row in rows:
            blob = f"{row.section_number} {row.section_title} {row.section_label}".lower()
            if needle and needle in blob:
                hits.append(row.section_root_id)
        return tuple(dict.fromkeys(hits))[:max_hits]

    # clause / section
    scored = []
    for row in rows:
        sc = _score_clause_hit(ref, row)
        if sc >= 0:
            scored.append((sc, row.section_root_id))
    scored.sort(key=lambda x: (-x[0], x[1]))
    if not scored:
        return ()
    # Drop weak appendix collisions when a solid body hit exists.
    best = scored[0][0]
    filtered = [sid for sc, sid in scored if sc >= best - 1.5][:max_hits]
    return tuple(dict.fromkeys(filtered))


def collect_follow_section_ids(
    texts: Iterable[str],
    outline: Sequence[Any],
    *,
    extra_raw_refs: Sequence[str] = (),
    max_refs: int = 6,
    max_sections: int = 3,
) -> Tuple[Tuple[str, ...], List[ContractRefTarget]]:
    """Parse many text snippets and resolve unique follow targets."""
    refs: List[ContractRefTarget] = []
    seen = set()
    for text in texts:
        for ref in parse_contract_cross_references(text or "", limit=max_refs):
            key = ref.normalized_key
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    for raw in extra_raw_refs:
        for ref in parse_contract_cross_references(str(raw or ""), limit=2):
            key = ref.normalized_key
            if key in seen:
                continue
            seen.add(key)
            refs.append(ref)

    # Prefer appendix / appendix_clause before plain clauses.
    kind_rank = {"appendix_clause": 0, "appendix": 1, "clause": 2, "quote": 3}
    refs.sort(key=lambda r: (kind_rank.get(r.kind, 9), -r.confidence))

    section_ids: List[str] = []
    used_refs: List[ContractRefTarget] = []
    for ref in refs[:max_refs]:
        hits = resolve_ref_to_section_root_ids(ref, outline, max_hits=2)
        if not hits:
            continue
        used_refs.append(ref)
        for sid in hits:
            if sid not in section_ids:
                section_ids.append(sid)
            if len(section_ids) >= max_sections:
                return tuple(section_ids), used_refs
    return tuple(section_ids), used_refs
