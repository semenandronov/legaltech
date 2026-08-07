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


def _iter_norm_to_raw_map(original: str) -> List[int]:
    """
    For each character index in whitespace-normalized text, the raw offset in ``original``.

    Normalization matches ``_normalize_quote_for_locate`` (collapse whitespace/bullets).
    """
    mapping: List[int] = []
    prev_space = True
    for i, ch in enumerate(original):
        if ch.isspace() or ch in "●•":
            if prev_space:
                continue
            mapping.append(i)
            prev_space = True
            continue
        mapping.append(i)
        prev_space = False
    return mapping


def _map_norm_range_to_raw(
    original: str,
    norm_start: int,
    norm_end: int,
) -> Optional[Tuple[int, int]]:
    """Map half-open [norm_start, norm_end) → raw [start, end) in ``original``."""
    if norm_end <= norm_start or norm_start < 0:
        return None
    mapping = _iter_norm_to_raw_map(original)
    if not mapping or norm_start >= len(mapping):
        return None
    raw_start = mapping[norm_start]
    if norm_end >= len(mapping):
        raw_end = len(original)
    else:
        raw_end = mapping[norm_end]
    if raw_end <= raw_start:
        return None
    return raw_start, raw_end


def span_faithfully_covers_quote(
    original: str,
    start: Optional[int],
    end: Optional[int],
    quote: str,
    *,
    max_leading_junk: int = 8,
) -> bool:
    """
    True when [start, end) is a highlight span for ``quote``, not a loose parent chunk.

    Requires the quote (whitespace-normalized) to begin near the start of the span.
    Containment alone is not enough — wide chunk spans always contain short quotes.
    """
    if start is None or end is None or end <= start or not original or not quote:
        return False
    try:
        s, e = int(start), int(end)
    except (TypeError, ValueError):
        return False
    if s < 0 or e > len(original) or e <= s:
        return False
    snippet = original[s:e]
    q_norm = _normalize_quote_for_locate(quote)
    sn_norm = _normalize_quote_for_locate(snippet)
    if not q_norm or not sn_norm:
        return False
    # Prefer full quote; fall back to a stable head for long OCR quotes.
    probes = [q_norm]
    if len(q_norm) > 64:
        probes.append(q_norm[:64])
    for probe in probes:
        idx = sn_norm.find(probe)
        if idx == -1:
            continue
        if idx <= max_leading_junk:
            return True
    return False


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

    Uses whitespace-normalized matching so OCR line breaks do not block narrowing.
    Falls back to the full span only if the quote cannot be located inside it.
    """
    if not original or span_end <= span_start:
        return span_start, span_end
    q = (quote_anchor or "").strip()
    if len(q) < min_quote_len:
        return span_start, span_end
    chunk = original[span_start:span_end]
    if not chunk:
        return span_start, span_end

    # Fast path: exact / casefold within the raw chunk.
    q_lower = q.lower().replace("\u2026", "").replace("...", "").strip()
    chunk_lower = chunk.lower()
    idx = chunk_lower.find(q_lower)
    if idx == -1 and len(q_lower) > 80:
        idx = chunk_lower.find(q_lower[:80])
        if idx != -1:
            return span_start + idx, span_start + idx + 80
    if idx != -1:
        return span_start + idx, span_start + idx + min(len(q), len(chunk) - idx)

    # OCR path: newlines in chunk vs spaces in quote (no recursion into locate).
    norm_chunk = _normalize_quote_for_locate(chunk)
    for probe in (
        _normalize_quote_for_locate(q),
        _normalize_quote_for_locate(q[:80]) if len(q) > 80 else "",
    ):
        if not probe or len(probe) < min_quote_len:
            continue
        use_probe = probe
        nidx = norm_chunk.find(probe)
        if nidx == -1 and len(probe) > 64:
            use_probe = probe[:64]
            nidx = norm_chunk.find(use_probe)
        if nidx == -1:
            continue
        mapped = _map_norm_range_to_raw(chunk, nidx, nidx + len(use_probe))
        if mapped is None:
            continue
        local_s, local_e = mapped
        if len(use_probe) < len(_normalize_quote_for_locate(q)):
            local_e = min(len(chunk), local_s + max(len(q), local_e - local_s))
        return span_start + local_s, span_start + local_e
    return span_start, span_end


def locate_quote_in_original(
    original: str,
    quote_anchor: str,
    *,
    min_quote_len: int = 12,
) -> Optional[Tuple[int, int]]:
    """
    Find quote_anchor inside the full document text.

    Returns a half-open [start, end) span that begins at the quote itself.
    Never returns a parent-chunk window padded before the match (that caused
    PDF highlights to start ~40 characters early on OCR preambles).
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
        span_len = len(probe)
        if idx == -1 and len(probe) > 80:
            idx = raw_lower.find(probe[:80])
            span_len = 80
        if idx != -1:
            end = min(len(original), idx + max(span_len, min(len(q), len(original) - idx)))
            if end > idx and span_faithfully_covers_quote(original, idx, end, q):
                return idx, end
            if end > idx:
                # Raw probe matched; trim trailing overshoot via narrow on a tight window.
                ns, ne = narrow_char_span_to_quote(
                    original=original,
                    span_start=idx,
                    span_end=min(len(original), idx + max(len(q) + 40, span_len + 40)),
                    quote_anchor=q,
                    min_quote_len=min_quote_len,
                )
                if span_faithfully_covers_quote(original, ns, ne, q):
                    return ns, ne
                return idx, end

    norm_original = _normalize_quote_for_locate(original)
    norm_probes: List[str] = []
    for candidate in (_normalize_quote_for_locate(q), _normalize_quote_for_locate(q.lstrip("●•·-–— "))):
        if candidate and len(candidate) >= min_quote_len and candidate not in norm_probes:
            norm_probes.append(candidate)

    for probe in norm_probes:
        use_probe = probe
        idx = norm_original.find(probe)
        if idx == -1 and len(probe) > 80:
            use_probe = probe[:80]
            idx = norm_original.find(use_probe)
        if idx == -1:
            continue
        mapped = _map_norm_range_to_raw(original, idx, idx + len(use_probe))
        if mapped is None:
            continue
        raw_start, raw_end = mapped
        # Extend raw_end toward full quote length when probe was truncated.
        if len(use_probe) < len(probe):
            raw_end = min(len(original), raw_start + max(len(q), raw_end - raw_start))
        if span_faithfully_covers_quote(original, raw_start, raw_end, q):
            return raw_start, raw_end
        # Tighten within a local window starting at the mapped match — never pad left.
        ns, ne = narrow_char_span_to_quote(
            original=original,
            span_start=raw_start,
            span_end=min(len(original), raw_start + max(len(q) + 80, raw_end - raw_start + 40)),
            quote_anchor=q,
            min_quote_len=min_quote_len,
        )
        if span_faithfully_covers_quote(original, ns, ne, q):
            return ns, ne
        if raw_end > raw_start:
            return raw_start, raw_end
    return None


def _norm_index_to_raw(original: str, norm_index: int) -> Optional[int]:
    """Map an index in whitespace/bullet-normalized text back to raw offset."""
    mapping = _iter_norm_to_raw_map(original)
    if norm_index < 0 or norm_index >= len(mapping):
        return None
    return mapping[norm_index]


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
    "span_faithfully_covers_quote",
]
