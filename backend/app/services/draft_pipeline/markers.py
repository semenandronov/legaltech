"""Canonical gap markers for missing draft fields."""
from __future__ import annotations

import re
from typing import List, Tuple

# Inline marker when a fact is unknown — UI can highlight later.
LEGACY_GAP_PATTERN = re.compile(r"\[\?\s*(.+?)\s*\?\]", re.DOTALL)
GAP_MARKER_PATTERN = re.compile(r"\[(?!\?)([^\[\]]+)\]")
LEGACY_FILL = re.compile(r"\[ЗАПОЛНИТЬ\]", re.IGNORECASE)


def gap_marker(label: str) -> str:
    """Build a canonical gap marker, e.g. [ИНН должника]."""
    text = (label or "данные").strip()
    text = re.sub(r"\s+", " ", text)
    return f"[{text}]"


def find_gap_markers(text: str) -> List[Tuple[str, int, int]]:
    """Return list of (label, start, end) for each gap marker in text."""
    out: List[Tuple[str, int, int]] = []
    source = text or ""
    seen_spans: set[tuple[int, int]] = set()

    for m in LEGACY_GAP_PATTERN.finditer(source):
        span = (m.start(), m.end())
        if span not in seen_spans:
            seen_spans.add(span)
            out.append((m.group(1).strip(), m.start(), m.end()))

    for m in GAP_MARKER_PATTERN.finditer(source):
        span = (m.start(), m.end())
        if span in seen_spans:
            continue
        if any(start <= m.start() and m.end() <= end for start, end in seen_spans):
            continue
        seen_spans.add(span)
        out.append((m.group(1).strip(), m.start(), m.end()))

    out.sort(key=lambda item: item[1])
    return out


def normalize_legacy_fillers(text: str) -> str:
    """Convert legacy [ЗАПОЛНИТЬ] and [? … ?] to canonical [поле] markers."""
    if not text:
        return text
    text = LEGACY_GAP_PATTERN.sub(lambda m: gap_marker(m.group(1).strip()), text)
    return LEGACY_FILL.sub(lambda _: gap_marker("заполнить"), text)


def html_tag_balance_ok(html: str) -> bool:
    """Basic check: equal open/close counts for common block tags."""
    if not html:
        return True
    tags = ("p", "section", "article", "div", "table", "tr", "td", "ol", "ul", "li", "h1", "h2", "h3")
    for tag in tags:
        opens = len(re.findall(rf"<\s*{tag}\b", html, re.IGNORECASE))
        closes = len(re.findall(rf"<\s*/\s*{tag}\s*>", html, re.IGNORECASE))
        if opens != closes:
            return False
    return True
