"""
Provenance spans: char-range ↔ OCR/Docling bbox mapping for chunks and citations.

Yandex OCR emits one bbox per text block. LegalChunkerV2 must attach only the blocks
whose char span overlaps a chunk (macro/micro) or a citation span — not the whole macro.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

ProvSpan = Tuple[int, int, List[Dict[str, Any]]]


def char_spans_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """True if half-open intervals [a_start, a_end) and [b_start, b_end) intersect."""
    if a_end <= a_start or b_end <= b_start:
        return False
    return a_start < b_end and b_start < a_end


def annotate_prov_items_char_span(
    prov_items: Sequence[Dict[str, Any]],
    char_start: int,
    char_end: int,
) -> List[Dict[str, Any]]:
    """Copy prov dicts and stamp document-level char offsets for each block."""
    out: List[Dict[str, Any]] = []
    cs, ce = int(char_start), int(char_end)
    for p in prov_items:
        if not isinstance(p, dict):
            continue
        row = dict(p)
        row["char_start"] = cs
        row["char_end"] = ce
        out.append(row)
    return out


def collect_prov_spans_from_segments(
    segments: Sequence[Any],
) -> List[ProvSpan]:
    """Build (char_start, char_end, prov_items) from chunker segments."""
    spans: List[ProvSpan] = []
    for seg in segments:
        prov = getattr(seg, "prov_items", None) or []
        if not prov:
            continue
        cs = int(getattr(seg, "char_start", 0) or 0)
        ce = int(getattr(seg, "char_end", 0) or 0)
        if ce <= cs:
            continue
        spans.append(
            (
                cs,
                ce,
                annotate_prov_items_char_span(prov, cs, ce),
            )
        )
    return spans


def prov_items_for_char_span(
    prov_spans: Sequence[ProvSpan],
    char_start: int,
    char_end: int,
) -> List[Dict[str, Any]]:
    """
    Prov entries whose stamped char span overlaps [char_start, char_end).
    Deduplicates by (page_no, rounded bbox).
    """
    if char_end <= char_start:
        return []
    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for span_start, span_end, prov_list in prov_spans:
        if not char_spans_overlap(span_start, span_end, char_start, char_end):
            continue
        for p in prov_list:
            if not isinstance(p, dict):
                continue
            key = _prov_dedupe_key(p)
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(p))
    return out


def _prov_dedupe_key(prov: Dict[str, Any]) -> Tuple[Any, ...]:
    bbox = prov.get("bbox")
    if isinstance(bbox, dict):
        try:
            return (
                prov.get("page_no"),
                round(float(bbox.get("l", 0)), 4),
                round(float(bbox.get("t", 0)), 4),
                round(float(bbox.get("r", 0)), 4),
                round(float(bbox.get("b", 0)), 4),
            )
        except (TypeError, ValueError):
            pass
    return (prov.get("page_no"), prov.get("char_start"), prov.get("char_end"))


def dl_meta_prov_entries(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten dl_meta.doc_items[].prov[] to a list of prov dicts."""
    if not isinstance(meta, dict):
        return []
    dl_meta = meta.get("dl_meta")
    if not isinstance(dl_meta, dict):
        return []
    doc_items = dl_meta.get("doc_items")
    if not isinstance(doc_items, list):
        return []
    out: List[Dict[str, Any]] = []
    for doc_item in doc_items:
        if not isinstance(doc_item, dict):
            continue
        prov_list = doc_item.get("prov")
        if not isinstance(prov_list, list):
            continue
        for prov in prov_list:
            if isinstance(prov, dict):
                out.append(prov)
    return out


def prov_entries_have_char_spans(meta: Dict[str, Any]) -> bool:
    """True if indexed dl_meta prov includes char_start/char_end (post-fix index)."""
    for prov in dl_meta_prov_entries(meta):
        if prov.get("char_start") is not None and prov.get("char_end") is not None:
            return True
    return False


def filter_prov_entries_for_char_span(
    prov_entries: Sequence[Dict[str, Any]],
    char_start: int,
    char_end: int,
) -> List[Dict[str, Any]]:
    """Keep prov entries overlapping [char_start, char_end); dedupe."""
    if char_end <= char_start:
        return []
    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for p in prov_entries:
        if not isinstance(p, dict):
            continue
        ps = p.get("char_start")
        pe = p.get("char_end")
        if ps is not None and pe is not None:
            try:
                if not char_spans_overlap(int(ps), int(pe), char_start, char_end):
                    continue
            except (TypeError, ValueError):
                pass
        key = _prov_dedupe_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _normalize_quote_for_locate(value: str) -> str:
    cleaned = (
        (value or "")
        .lower()
        .replace("\u2026", "")
        .replace("...", "")
        .replace("●", " ")
        .replace("•", " ")
    )
    return " ".join(cleaned.split())


def narrow_char_span_to_quote(
    *,
    original: str,
    span_start: int,
    span_end: int,
    quote_anchor: str,
    min_quote_len: int = 12,
) -> Tuple[int, int]:
    """
    Shrink [span_start, span_end) to the substring matching quote_anchor when possible.
    Falls back to the full span if the quote cannot be located.
    """
    if not original or span_end <= span_start:
        return span_start, span_end
    q = (quote_anchor or "").strip()
    if len(q) < min_quote_len:
        return span_start, span_end
    chunk = original[span_start:span_end]
    if not chunk:
        return span_start, span_end
    q_lower = q.lower().replace("\u2026", "").replace("...", "").strip()
    chunk_lower = chunk.lower()
    idx = chunk_lower.find(q_lower)
    if idx == -1 and len(q_lower) > 80:
        idx = chunk_lower.find(q_lower[:80])
    if idx == -1:
        return span_start, span_end
    q_len = min(len(q), len(chunk) - idx)
    return span_start + idx, span_start + idx + q_len


def locate_quote_in_original(
    original: str,
    quote_anchor: str,
    *,
    min_quote_len: int = 12,
) -> Optional[Tuple[int, int]]:
    """
    Find quote_anchor inside the full document text.

    Returns a half-open [start, end) span in ``original``, or None when not found.
    """
    if not original:
        return None
    q = (quote_anchor or "").strip()
    if not q:
        return None

    raw_lower = original.lower()
    # Short quotes: exact locate only (avoid accidental matches on tiny probes).
    if len(q) < min_quote_len:
        idx = raw_lower.find(q.lower())
        if idx != -1:
            return idx, idx + len(q)
        return None

    raw_probes: List[str] = []
    for candidate in (
        q.lower().replace("\u2026", "").replace("...", "").strip(),
        q.lstrip("●•·-–— ").strip().lower(),
    ):
        if candidate and len(candidate) >= min_quote_len and candidate not in raw_probes:
            raw_probes.append(candidate)

    for probe in raw_probes:
        idx = raw_lower.find(probe)
        if idx == -1 and len(probe) > 80:
            idx = raw_lower.find(probe[:80])
            span_len = 80
        else:
            span_len = len(probe)
        if idx != -1:
            end = min(len(original), idx + max(span_len, min(len(q), len(original) - idx)))
            if end > idx:
                return idx, end

    norm_original = _normalize_quote_for_locate(original)
    norm_probes: List[str] = []
    for candidate in (_normalize_quote_for_locate(q), _normalize_quote_for_locate(q.lstrip("●•·-–— "))):
        if candidate and len(candidate) >= min_quote_len and candidate not in norm_probes:
            norm_probes.append(candidate)

    for probe in norm_probes:
        idx = norm_original.find(probe)
        if idx == -1 and len(probe) > 80:
            idx = norm_original.find(probe[:80])
        if idx == -1:
            continue
        raw_start = _norm_index_to_raw(original, idx)
        if raw_start is None:
            continue
        ns, ne = narrow_char_span_to_quote(
            original=original,
            span_start=max(0, raw_start - 40),
            span_end=min(len(original), raw_start + max(len(q), len(probe)) + 80),
            quote_anchor=q,
            min_quote_len=min_quote_len,
        )
        head = probe[: min(40, len(probe))]
        if head and head in _normalize_quote_for_locate(original[ns:ne]):
            return ns, ne
        raw_end = min(len(original), raw_start + max(len(q), len(probe)))
        if raw_end > raw_start:
            return raw_start, raw_end
    return None


def _norm_index_to_raw(original: str, norm_index: int) -> Optional[int]:
    """Map an index in whitespace/bullet-normalized text back to raw offset."""
    if norm_index < 0:
        return None
    norm_pos = 0
    prev_space = True
    for i, ch in enumerate(original):
        if ch.isspace() or ch in "●•":
            if prev_space:
                continue
            if norm_pos == norm_index:
                return i
            norm_pos += 1
            prev_space = True
            continue
        if norm_pos == norm_index:
            return i
        norm_pos += 1
        prev_space = False
    return None


__all__ = [
    "ProvSpan",
    "annotate_prov_items_char_span",
    "char_spans_overlap",
    "collect_prov_spans_from_segments",
    "dl_meta_prov_entries",
    "filter_prov_entries_for_char_span",
    "locate_quote_in_original",
    "narrow_char_span_to_quote",
    "prov_entries_have_char_spans",
    "prov_items_for_char_span",
]
