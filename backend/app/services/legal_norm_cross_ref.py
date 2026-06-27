"""Парсинг и классификация отсылочных конструкций в текстах НПА."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from app.services.legal_instruments import INSTRUMENTS, resolve_instrument

# «ст. 61.3», «статья 10», «статьей 3 настоящего ФЗ», «п. 2 ст. 10 ГК РФ»
_ARTICLE_WORD_RE = r"стат(?:ья|ьи|ье|ью|ьей|ей|ьми|ями)"
_ARTICLE_SIMPLE_RE = re.compile(
    rf"(?:ст\.?|{_ARTICLE_WORD_RE})\s*(?P<article>\d+(?:[.,]\d+)*)",
    re.IGNORECASE,
)
_CLAUSE_PREFIX_RE = re.compile(
    r"(?:п\.?|пункт(?:а|ом|ы|ах)?)\s*(?P<clause>\d+(?:[.,]\d+)*)\s*",
    re.IGNORECASE,
)
_PART_PREFIX_RE = re.compile(
    r"(?:ч\.?|част(?:ь|и|ью))\s*(?P<part>\d+(?:[.,]\d+)*)\s*",
    re.IGNORECASE,
)

_INSTRUMENT_HINT_RE = re.compile(
    r"(?P<hint>"
    r"127\s*[-–]?\s*фз|фз\s*[-–]?\s*127|закон\s+о\s+банкротстве|несостоятельност"
    r"|гк\s*рф|гражданск(?:ий|ого)\s+кодекс"
    r"|апк\s*рф|арбитражн(?:ый|ого)\s+процессуальн"
    r"|гпк\s*рф|гражданск(?:ий|ого)\s+процессуальн"
    r"|пленум\s*(?:№|#)?\s*63|пп\s+вас\s*63"
    r")",
    re.IGNORECASE,
)

_FORWARD_MARKERS = (
    "в порядке",
    "в соответствии с",
    "предусмотрен",
    "установлен",
    "применя",
    "руководству",
    "согласно",
)

# «пункте 2 статьи 61.1», «п. 2 ст. 10»
_CLAUSE_ARTICLE_COMPOUND_RE = re.compile(
    r"пункт(?:е|а|у|ом)?\s+(?P<clause>\d+(?:\.\d+)*)\s+"
    rf"стать(?:и|ье|ью|ьей|ей)\s+(?P<article>\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
_P_CLAUSE_ST_RE = re.compile(
    r"п\.?\s*(?P<clause>\d+(?:\.\d+)*)\s+ст\.?\s*(?P<article>\d+(?:\.\d+)*)",
    re.IGNORECASE,
)
_SAME_ARTICLE_CLAUSE_RE = re.compile(
    r"пункт(?:е|а|у|ом)?\s+(?P<clause>\d+(?:\.\d+)*)\s+настоящ(?:ей|его|ая|ий)\s+стать",
    re.IGNORECASE,
)
_SAME_LAW_ARTICLE_RE = re.compile(
    rf"(?:ст\.?|{_ARTICLE_WORD_RE})\s*(?P<article>\d+(?:\.\d+)*)\s+"
    r"настоящ(?:его|его|им)\s+Федеральн(?:ого|ым)\s+закон",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedCrossRef:
    raw_text: str
    article_number: str
    clause_ref: str = ""
    part_ref: str = ""
    target_instrument_id: Optional[str] = None
    edge_type: str = "REFERENCES"


def normalize_article_number(value: Optional[str]) -> str:
    if not value:
        return ""
    v = str(value).strip().replace(",", ".")
    v = re.sub(r"\.+$", "", v)
    return v


def _resolve_instrument_hint(text: str, default_instrument_id: Optional[str]) -> Optional[str]:
    m = _INSTRUMENT_HINT_RE.search(text or "")
    if m:
        hint = (m.group("hint") or "").lower()
        for inst in INSTRUMENTS.values():
            if inst.instrument_id == "other":
                continue
            for alias in (inst.short_name, inst.instrument_id, *inst.aliases):
                a = (alias or "").lower()
                if a and a in hint:
                    return inst.instrument_id
        if "127" in hint or "банкрот" in hint or "несостоятель" in hint:
            return "fz-127"
        if "гк" in hint:
            return "gk-rf"
        if "апк" in hint:
            return "apk-rf"
        if "гпк" in hint:
            return "gpk-rf"
        if "63" in hint or "пленум" in hint:
            return "plenum-63"
    if default_instrument_id:
        return resolve_instrument(default_instrument_id).instrument_id if resolve_instrument(default_instrument_id) else default_instrument_id
    return default_instrument_id


def classify_edge_type(source_text: str, ref_span: Tuple[int, int]) -> str:
    """FORWARD_TO для отсылок «в порядке, установленном…» рядом с ref."""
    start = max(0, ref_span[0] - 120)
    window = (source_text or "")[start : ref_span[0]].lower()
    if any(marker in window for marker in _FORWARD_MARKERS):
        return "FORWARD_TO"
    return "REFERENCES"


def parse_cross_reference(
    raw: str,
    *,
    source_text: str = "",
    default_instrument_id: Optional[str] = None,
) -> Optional[ParsedCrossRef]:
    text = (raw or "").strip()
    if not text:
        return None
    m = _ARTICLE_SIMPLE_RE.search(text)
    if not m:
        return None
    article = normalize_article_number(m.group("article"))
    if not article:
        return None
    prefix = text[: m.start()]
    clause_m = _CLAUSE_PREFIX_RE.search(prefix)
    part_m = _PART_PREFIX_RE.search(prefix)
    clause = normalize_article_number(clause_m.group("clause") if clause_m else "")
    part = normalize_article_number(part_m.group("part") if part_m else "")
    clause_ref = clause or part
    target_iid = _resolve_instrument_hint(text, default_instrument_id)
    body = source_text or text
    ref_pos = body.lower().find(text.lower())
    if ref_pos >= 0:
        span = (ref_pos, ref_pos + len(text))
    else:
        span = m.span()
    edge_type = classify_edge_type(body, span)
    return ParsedCrossRef(
        raw_text=text,
        article_number=article,
        clause_ref=clause_ref,
        part_ref=part,
        target_instrument_id=target_iid,
        edge_type=edge_type,
    )


def parse_cross_references_from_text(
    text: str,
    *,
    default_instrument_id: Optional[str] = None,
    source_article_number: Optional[str] = None,
    source_clause_ref: Optional[str] = None,
    max_refs: int = 48,
) -> List[ParsedCrossRef]:
    if not text:
        return []
    out: List[ParsedCrossRef] = []
    seen: set[str] = set()

    def _append(parsed: Optional[ParsedCrossRef]) -> None:
        if not parsed:
            return
        key = (
            f"{parsed.target_instrument_id}|{parsed.article_number}|"
            f"{parsed.clause_ref}|{parsed.edge_type}|{parsed.raw_text.lower()}"
        )
        if key in seen:
            return
        seen.add(key)
        out.append(parsed)

    for m in _CLAUSE_ARTICLE_COMPOUND_RE.finditer(text):
        article = normalize_article_number(m.group("article"))
        clause = normalize_article_number(m.group("clause"))
        raw = m.group(0).strip()
        span = m.span()
        target_iid = _resolve_instrument_hint(text[span[0] : span[1] + 80], default_instrument_id)
        _append(
            ParsedCrossRef(
                raw_text=raw,
                article_number=article,
                clause_ref=clause,
                target_instrument_id=target_iid,
                edge_type=classify_edge_type(text, span),
            )
        )

    for m in _P_CLAUSE_ST_RE.finditer(text):
        article = normalize_article_number(m.group("article"))
        clause = normalize_article_number(m.group("clause"))
        raw = m.group(0).strip()
        span = m.span()
        target_iid = _resolve_instrument_hint(text[span[0] : span[1] + 80], default_instrument_id)
        _append(
            ParsedCrossRef(
                raw_text=raw,
                article_number=article,
                clause_ref=clause,
                target_instrument_id=target_iid,
                edge_type=classify_edge_type(text, span),
            )
        )

    if source_article_number:
        for m in _SAME_ARTICLE_CLAUSE_RE.finditer(text):
            clause = normalize_article_number(m.group("clause"))
            raw = m.group(0).strip()
            span = m.span()
            _append(
                ParsedCrossRef(
                    raw_text=raw,
                    article_number=normalize_article_number(source_article_number),
                    clause_ref=clause,
                    target_instrument_id=default_instrument_id,
                    edge_type=classify_edge_type(text, span),
                )
            )

    for m in _SAME_LAW_ARTICLE_RE.finditer(text):
        article = normalize_article_number(m.group("article"))
        raw = m.group(0).strip()
        span = m.span()
        _append(
            ParsedCrossRef(
                raw_text=raw,
                article_number=article,
                clause_ref="",
                target_instrument_id=default_instrument_id,
                edge_type=classify_edge_type(text, span),
            )
        )

    for m in _ARTICLE_SIMPLE_RE.finditer(text):
        start = m.start()
        window_start = max(0, start - 80)
        art_raw = m.group(0).strip()
        prefix = text[window_start:start]
        clause_m = _CLAUSE_PREFIX_RE.search(prefix)
        raw = f"{clause_m.group(0).strip()} {art_raw}" if clause_m else art_raw
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        parsed = parse_cross_reference(
            raw,
            source_text=text,
            default_instrument_id=default_instrument_id,
        )
        _append(parsed)
        if len(out) >= max_refs:
            break
    return out[:max_refs]


def make_norm_node_key(
    instrument_id: str,
    article_number: str,
    *,
    clause_ref: str = "",
) -> str:
    iid = (instrument_id or "unknown").strip().lower()
    art = normalize_article_number(article_number)
    if clause_ref:
        cref = normalize_article_number(clause_ref)
        return f"{iid}::art::{art}::clause::{cref}"
    return f"{iid}::art::{art}"


def is_clause_level_norm_key(norm_node_key: str) -> bool:
    return "::clause::" in (norm_node_key or "")


def parse_article_from_norm_key(norm_node_key: str) -> Optional[Tuple[str, str]]:
    """instrument_id, article_number для ключа уровня статьи (без ::clause::)."""
    nk = (norm_node_key or "").strip()
    if not nk or is_clause_level_norm_key(nk):
        return None
    if "::art::" not in nk:
        return None
    iid, art = nk.split("::art::", 1)
    iid = iid.strip().lower()
    art = normalize_article_number(art.strip())
    if not iid or not art:
        return None
    return iid, art


def make_full_path(
    instrument_short_name: str,
    parent_path: Sequence[str],
    section_title: str,
) -> str:
    parts: List[str] = []
    if (instrument_short_name or "").strip():
        parts.append(instrument_short_name.strip())
    for p in parent_path or []:
        t = (p or "").strip()
        if t and t not in parts:
            parts.append(t)
    st = (section_title or "").strip()
    if st and st not in parts:
        parts.append(st)
    return " > ".join(parts)
