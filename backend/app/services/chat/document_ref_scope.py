"""
Deterministic document-number → file_id scope.

When a question cites «договор №54» / «№98/2024», resolve target files from the
case catalog (filename + summary + key_points) before chunk hybrid search.

This is a first-class router stage — not an ad-hoc golden-case branch.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set

# Shared with passport / escalation: «№54», «№ 98/2024», optional «договор …» prefix.
CONTRACT_NO_RE = re.compile(
    r"(?i)(?:договор\w*\s+(?:поставки|подряда|купли[-\s]?продажи)?\s*)?№\s*([0-9]+(?:/[0-9]+)?)"
)


def normalize_doc_ref(raw: str) -> str:
    """Canonical form: digits, optional /year, no spaces."""
    s = (raw or "").strip().lower().replace(" ", "").replace("\u00a0", "")
    s = s.lstrip("№#")
    return s


def extract_document_refs(text: str) -> List[str]:
    """Ordered unique contract/document numbers mentioned in text."""
    found: List[str] = []
    seen: Set[str] = set()
    for match in CONTRACT_NO_RE.finditer(text or ""):
        ref = normalize_doc_ref(match.group(1))
        if not ref or ref in seen:
            continue
        seen.add(ref)
        found.append(ref)
    return found


def _catalog_blob(entry: object) -> str:
    parts = [
        str(getattr(entry, "filename", "") or ""),
        str(getattr(entry, "summary", "") or ""),
    ]
    kps = getattr(entry, "key_points", None) or []
    if isinstance(kps, (list, tuple)):
        parts.extend(str(x) for x in kps if x)
    elif isinstance(entry, dict):
        parts = [
            str(entry.get("filename") or ""),
            str(entry.get("summary") or ""),
        ]
        kps = entry.get("key_points") or []
        if isinstance(kps, (list, tuple)):
            parts.extend(str(x) for x in kps if x)
    return "\n".join(parts)


def catalog_entry_doc_refs(entry: object) -> Set[str]:
    return set(extract_document_refs(_catalog_blob(entry)))


def match_catalog_by_document_refs(
    catalog: Sequence[object],
    question: str,
    *,
    limit: int = 3,
) -> List[str]:
    """
    Exact catalog match: every question doc-ref must appear in a file's
    filename/summary/key_points for that file to score; files matching more
    refs rank higher. Ambiguous multi-file ties keep all top matches up to limit.
    """
    q_refs = extract_document_refs(question)
    if not q_refs or not catalog:
        return []

    scored: List[tuple[int, str]] = []
    for entry in catalog:
        file_id = str(getattr(entry, "file_id", None) or (entry.get("file_id") if isinstance(entry, dict) else "") or "").strip()
        if not file_id:
            continue
        entry_refs = catalog_entry_doc_refs(entry)
        if not entry_refs:
            continue
        overlap = sum(1 for r in q_refs if r in entry_refs)
        if overlap <= 0:
            continue
        # Prefer files that cover the cited refs; require full cover when one ref asked.
        if len(q_refs) == 1 and q_refs[0] not in entry_refs:
            continue
        scored.append((overlap, file_id))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][0]
    # Keep only top-score files (exact identity), then cap.
    out: List[str] = []
    seen: Set[str] = set()
    for score, fid in scored:
        if score < best:
            break
        if fid in seen:
            continue
        seen.add(fid)
        out.append(fid)
        if len(out) >= max(1, limit):
            break
    return out


_CROSS_DOC_KIND_RE = re.compile(
    r"(?i)\b(возражен\w*|ходатайств\w*|иск\w*|заявлен\w*|определен\w*|решен\w*)\b"
)


def match_related_catalog_files(
    catalog: Sequence[object],
    question: str,
    *,
    exclude_ids: Optional[Iterable[str]] = None,
    limit: int = 2,
) -> List[str]:
    """
    When the question cites a contract AND another pleading kind (возражения, иск…),
    pull those related files so linkage questions are not locked to one PDF.
    """
    if not _CROSS_DOC_KIND_RE.search(question or ""):
        return []
    excluded = {str(x).strip() for x in (exclude_ids or []) if str(x).strip()}
    kinds = [m.group(1).lower() for m in _CROSS_DOC_KIND_RE.finditer(question or "")]
    if not kinds:
        return []
    scored: List[tuple[float, str]] = []
    for entry in catalog:
        file_id = str(
            getattr(entry, "file_id", None)
            or (entry.get("file_id") if isinstance(entry, dict) else "")
            or ""
        ).strip()
        if not file_id or file_id in excluded:
            continue
        blob = _catalog_blob(entry).lower()
        score = 0.0
        for kind in kinds:
            stem = kind[:6]
            if stem and stem in blob:
                score += 2.0
        if score <= 0:
            continue
        scored.append((score, file_id))
    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[str] = []
    seen: Set[str] = set()
    for _, fid in scored:
        if fid in seen:
            continue
        seen.add(fid)
        out.append(fid)
        if len(out) >= max(1, limit):
            break
    return out


def resolve_document_ref_file_ids(
    catalog: Sequence[object],
    question: str,
    *,
    limit: int = 3,
    include_related: bool = True,
) -> List[str]:
    """Public helper used by CaseRetrievalRouter."""
    primary = match_catalog_by_document_refs(catalog, question, limit=limit)
    if not primary:
        return []
    if not include_related:
        return primary
    related = match_related_catalog_files(
        catalog, question, exclude_ids=primary, limit=max(1, limit - 1)
    )
    merged: List[str] = []
    seen: Set[str] = set()
    for fid in list(primary) + list(related):
        if fid in seen:
            continue
        seen.add(fid)
        merged.append(fid)
        if len(merged) >= max(1, limit + 1):
            break
    return merged


def question_refs_bound_to_files(
    question: str,
    *,
    catalog: Optional[Sequence[object]] = None,
    file_ids: Optional[Iterable[str]] = None,
    file_ref_index: Optional[dict] = None,
) -> bool:
    """
    True when question cites doc numbers and those numbers map to the given
    scoped file_ids (via catalog or precomputed file_id→refs index).
    """
    q_refs = set(extract_document_refs(question))
    if not q_refs:
        return False
    scoped = {str(x).strip() for x in (file_ids or []) if str(x).strip()}
    if not scoped:
        return False

    if file_ref_index:
        covered: Set[str] = set()
        for fid in scoped:
            covered |= set(file_ref_index.get(fid) or [])
        return bool(q_refs & covered)

    if not catalog:
        return False
    matched = set(match_catalog_by_document_refs(catalog, question, limit=8))
    return bool(matched & scoped)
