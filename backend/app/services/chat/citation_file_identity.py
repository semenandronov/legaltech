"""
Resolve case file UUID + display name for citation SSE (never synthetic doc_N labels).

UI contract: source_id must be File.id in the case, not D/C prompt labels or RAG fallbacks.
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_SYNTHETIC_DOC_ID_RE = re.compile(r"^doc_?\d+$", re.IGNORECASE)
_PASSPORT_FILE_LINE_RE = re.compile(r"^Файл:\s*(.+?)\s*$", re.MULTILINE)


def _norm_filename(name: str) -> str:
    return (name or "").strip().casefold()


def is_synthetic_doc_label(value: Any) -> bool:
    """Prompt/RAG placeholder (doc_1, doc_0), not a case File.id."""
    s = str(value or "").strip()
    if not s or s.lower() in {"unknown", "none", "null"}:
        return True
    return bool(_SYNTHETIC_DOC_ID_RE.match(s))


def is_plausible_case_file_id(value: Any, *, known_ids: Optional[set[str]] = None) -> bool:
    """True when value is a real case file id (catalog member or UUID-shaped)."""
    s = str(value or "").strip()
    if not s or is_synthetic_doc_label(s):
        return False
    if known_ids is not None:
        return s in known_ids
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        # Legacy non-UUID ids: accept only if long enough to not be doc_N
        return len(s) >= 12 and not is_synthetic_doc_label(s)


@dataclass
class CaseCitationFileIndex:
    """Case file catalog for citation source_id resolution."""

    file_id_to_name: Dict[str, str] = field(default_factory=dict)
    name_to_file_id: Dict[str, str] = field(default_factory=dict)
    ordered_file_ids: List[str] = field(default_factory=list)

    @property
    def known_ids(self) -> set[str]:
        return set(self.file_id_to_name.keys())

    @classmethod
    def from_file_map(
        cls,
        file_id_to_name: Dict[str, str],
        *,
        ordered_file_ids: Optional[List[str]] = None,
    ) -> CaseCitationFileIndex:
        ordered = list(ordered_file_ids or []) or list(file_id_to_name.keys())
        name_map: Dict[str, str] = {}
        for fid, fn in file_id_to_name.items():
            key = _norm_filename(fn)
            if key and key not in name_map:
                name_map[key] = str(fid)
        return cls(
            file_id_to_name=dict(file_id_to_name),
            name_to_file_id=name_map,
            ordered_file_ids=[str(x) for x in ordered if x in file_id_to_name],
        )

    @classmethod
    def from_db(cls, db: Session, case_id: str) -> CaseCitationFileIndex:
        from app.services.chat.retrieval_router import build_case_file_catalog

        entries = build_case_file_catalog(db, case_id, limit=200)
        fmap = {str(e.file_id): str(e.filename or "Документ") for e in entries}
        order = [str(e.file_id) for e in entries]
        return cls.from_file_map(fmap, ordered_file_ids=order)

    def file_id_for_retrieval_d(self, retrieval_d: Optional[int]) -> Optional[str]:
        if retrieval_d is None or retrieval_d < 1:
            return None
        idx = int(retrieval_d) - 1
        if 0 <= idx < len(self.ordered_file_ids):
            return self.ordered_file_ids[idx]
        return None

    def file_id_for_filename(self, filename: str) -> Optional[str]:
        key = _norm_filename(filename)
        if not key or is_synthetic_doc_label(filename):
            return None
        return self.name_to_file_id.get(key)


def parse_passport_filename(page_content: str) -> Optional[str]:
    m = _PASSPORT_FILE_LINE_RE.search(page_content or "")
    if not m:
        return None
    name = (m.group(1) or "").strip()
    return name if name and not is_synthetic_doc_label(name) else None


def resolve_citation_file_identity(
    meta: Dict[str, Any],
    page_content: str,
    *,
    retrieval_d: Optional[int] = None,
    index: Optional[CaseCitationFileIndex] = None,
    d_to_file_id: Optional[Dict[int, str]] = None,
) -> Tuple[Optional[str], str]:
    """
    Return (file_id, display_file_name) for SSE citations.

    file_id is None only when the case catalog cannot map the fragment (UI: quote-only).
    """
    meta = dict(meta or {})
    known = index.known_ids if index else None
    pc = str(page_content or "")

    def _name_for(fid: str) -> str:
        if index and fid in index.file_id_to_name:
            return index.file_id_to_name[fid]
        return str(meta.get("source_file") or meta.get("filename") or "Документ")

    candidates: List[str] = []
    for key in ("file_id", "doc_id"):
        raw = meta.get(key)
        if raw is not None and str(raw).strip():
            candidates.append(str(raw).strip())

    for fid in candidates:
        if is_plausible_case_file_id(fid, known_ids=known):
            return fid, _name_for(fid)

    for name_key in ("filename", "source_file", "source_filename"):
        raw_name = meta.get(name_key)
        if raw_name is None:
            continue
        name = str(raw_name).strip()
        if not name or is_synthetic_doc_label(name):
            continue
        if index:
            fid = index.file_id_for_filename(name)
            if fid:
                return fid, index.file_id_to_name.get(fid, name)
        if is_plausible_case_file_id(name, known_ids=known):
            return name, _name_for(name)

    passport_name = parse_passport_filename(pc)
    if passport_name and index:
        fid = index.file_id_for_filename(passport_name)
        if fid:
            return fid, index.file_id_to_name.get(fid, passport_name)

    if retrieval_d is not None and d_to_file_id and retrieval_d in d_to_file_id:
        fid = d_to_file_id[retrieval_d]
        if fid and is_plausible_case_file_id(fid, known_ids=known):
            return fid, _name_for(fid)

    if index and retrieval_d is not None:
        fid = index.file_id_for_retrieval_d(retrieval_d)
        if fid:
            return fid, index.file_id_to_name.get(fid, _name_for(fid))

    # Legacy: synthetic doc_K sometimes aligned with 0-based chunk index K
    doc_id_raw = str(meta.get("doc_id") or "").strip()
    m = re.match(r"^doc_(\d+)$", doc_id_raw, re.IGNORECASE)
    if m and index:
        k = int(m.group(1))
        for ordinal in (k + 1, k, k + 2):
            fid = index.file_id_for_retrieval_d(ordinal)
            if fid:
                return fid, index.file_id_to_name.get(fid, _name_for(fid))

    display = passport_name or str(meta.get("source_file") or meta.get("filename") or "Документ")
    if is_synthetic_doc_label(display):
        display = passport_name or "Документ"
    return None, display


def collect_resolved_file_ids_for_originals(
    docs: List[Any],
    dc_labels: List[Tuple[int, int]],
    *,
    index: Optional[CaseCitationFileIndex],
) -> List[str]:
    """File ids to load original_text for — after identity resolution."""
    if not index:
        return []

    d_map: Dict[int, str] = {}
    out: List[str] = []
    seen: set[str] = set()

    for doc, (rd, _rc) in zip(docs, dc_labels):
        meta = dict(getattr(doc, "metadata", None) or {})
        pc = str(getattr(doc, "page_content", None) or "")
        fid, _ = resolve_citation_file_identity(
            meta, pc, retrieval_d=rd, index=index, d_to_file_id=d_map
        )
        if fid and fid not in seen:
            seen.add(fid)
            out.append(fid)
        if fid and rd not in d_map:
            d_map[rd] = fid
    return out
