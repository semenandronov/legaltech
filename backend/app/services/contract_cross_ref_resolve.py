"""Resolve contract cross-references (M&A + RU) to section hints."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

_SECTION_RE = re.compile(
    r"(?i)\b(?:section|article|§|sched\.?|schedule|exhibit|appendix|п\.?|пункт|раздел|статья)\s*"
    r"([0-9]+(?:\.[0-9]+)*)"
)
_QUOTED_RE = re.compile(r'"([^"]{2,80})"|«([^»]{2,80})»')


@dataclass(frozen=True)
class ContractRefTarget:
    kind: str
    anchor: str
    raw: str


def parse_contract_cross_references(text: str, *, limit: int = 12) -> List[ContractRefTarget]:
    """Extract section/schedule anchors from chunk text."""
    found: List[ContractRefTarget] = []
    seen = set()
    for match in _SECTION_RE.finditer(text or ""):
        anchor = match.group(1).strip()
        raw = match.group(0).strip()
        key = ("section", anchor)
        if key in seen:
            continue
        seen.add(key)
        found.append(ContractRefTarget(kind="section", anchor=anchor, raw=raw))
        if len(found) >= limit:
            return found
    for match in _QUOTED_RE.finditer(text or ""):
        quoted = (match.group(1) or match.group(2) or "").strip()
        if len(quoted) < 3:
            continue
        key = ("quote", quoted.lower())
        if key in seen:
            continue
        seen.add(key)
        found.append(ContractRefTarget(kind="quote", anchor=quoted, raw=quoted))
        if len(found) >= limit:
            break
    return found


def resolve_ref_to_section_root_ids(
    ref: ContractRefTarget,
    outline: Sequence[Tuple[str, str, str, str]],
) -> Tuple[str, ...]:
    """
    outline rows: (section_root_id, section_number, section_title, section_label)
    """
    anchor = ref.anchor
    hits: List[str] = []
    for sid, num, title, label in outline:
        blob = f"{num} {title} {label}"
        if ref.kind == "section":
            if anchor == num or num.startswith(anchor) or anchor.startswith(num):
                hits.append(sid)
            elif anchor in title or anchor in label:
                hits.append(sid)
        elif ref.kind == "quote":
            if anchor.lower() in blob.lower():
                hits.append(sid)
    return tuple(dict.fromkeys(hits))
