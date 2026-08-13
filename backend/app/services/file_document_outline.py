"""Persisted document outline (section_root map) for tabular context engineering."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.services.contract_cross_ref_resolve import (
    annotate_outline_containers,
    detect_appendix_heading,
    OutlineAnchorRow,
)

logger = logging.getLogger(__name__)

OUTLINE_PAYLOAD_KEY = "document_outline_v1"
_DEFINITION_TITLE_RE = re.compile(
    r"(?i)\b(?:definitions?|defined\s+terms?|interpretation|"
    r"определени[яе]|термины\s+и\s+определения)\b"
)


@dataclass(frozen=True)
class OutlineSectionEntry:
    section_root_id: str
    section_title: str
    section_number: str
    char_start: int
    char_end: int
    section_label: str = ""
    section_kind: str = "body"  # body | appendix | appendix_part
    appendix_no: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_root_id": self.section_root_id,
            "section_title": self.section_title,
            "section_number": self.section_number,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "section_label": self.section_label,
            "section_kind": self.section_kind,
            "appendix_no": self.appendix_no,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "OutlineSectionEntry":
        title = str(raw.get("section_title") or "").strip()
        label = str(raw.get("section_label") or "").strip()
        kind = str(raw.get("section_kind") or "").strip()
        app = str(raw.get("appendix_no") or "").strip()
        if not kind:
            kind, app = detect_appendix_heading(title, label)
        return cls(
            section_root_id=str(raw.get("section_root_id") or "").strip(),
            section_title=title,
            section_number=str(raw.get("section_number") or "").strip(),
            char_start=int(raw.get("char_start") or 0),
            char_end=int(raw.get("char_end") or 0),
            section_label=label,
            section_kind=kind or "body",
            appendix_no=app,
        )


def _int_meta(md: Dict[str, Any], key: str) -> int:
    try:
        return int(md.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def propagate_outline_appendix_containers(
    entries: Sequence[OutlineSectionEntry],
) -> List[OutlineSectionEntry]:
    """Stamp appendix containers and propagate appendix_no onto following parts."""
    rows = [
        OutlineAnchorRow(
            section_root_id=e.section_root_id,
            section_number=e.section_number,
            section_title=e.section_title,
            section_label=e.section_label,
            section_kind=e.section_kind or "body",
            appendix_no=e.appendix_no or "",
            char_start=e.char_start,
            char_end=e.char_end,
        )
        for e in entries
    ]
    annotated = annotate_outline_containers(rows)
    out: List[OutlineSectionEntry] = []
    for row in annotated:
        out.append(
            OutlineSectionEntry(
                section_root_id=row.section_root_id,
                section_title=row.section_title,
                section_number=row.section_number,
                char_start=row.char_start,
                char_end=row.char_end,
                section_label=row.section_label,
                section_kind=row.section_kind,
                appendix_no=row.appendix_no,
            )
        )
    return out


def _entries_with_appendix_propagation(
    entries: Sequence[OutlineSectionEntry],
) -> List[OutlineSectionEntry]:
    return propagate_outline_appendix_containers(entries)

def build_outline_from_chunks(chunks: Sequence[Document]) -> Tuple[List[OutlineSectionEntry], List[str]]:
    """Aggregate macro/micro chunks into one row per section_root_id."""
    by_root: Dict[str, Dict[str, Any]] = {}
    for doc in chunks or []:
        md = doc.metadata or {}
        level = str(md.get("chunk_level") or "").strip().lower()
        if level not in ("macro", "micro", ""):
            continue
        sid = str(md.get("section_root_id") or "").strip()
        if not sid:
            continue
        cs = _int_meta(md, "char_start")
        ce = _int_meta(md, "char_end")
        title = str(md.get("section_title") or "").strip()
        num = str(md.get("section_number") or "").strip()
        label = str(md.get("section_retrieval_label") or md.get("section_embedding_label") or "").strip()
        kind, app = detect_appendix_heading(title, label)
        row = by_root.get(sid)
        if row is None:
            by_root[sid] = {
                "section_root_id": sid,
                "section_title": title,
                "section_number": num,
                "char_start": cs,
                "char_end": ce,
                "section_label": label,
                "section_kind": kind,
                "appendix_no": app,
            }
            continue
        if cs and cs < int(row.get("char_start") or 0) or not row.get("char_start"):
            row["char_start"] = cs
            if title:
                row["section_title"] = title
                k2, a2 = detect_appendix_heading(title, label)
                row["section_kind"] = k2
                row["appendix_no"] = a2
            if num:
                row["section_number"] = num
        if ce > int(row.get("char_end") or 0):
            row["char_end"] = ce
        if label and not row.get("section_label"):
            row["section_label"] = label

    raw_entries = [
        OutlineSectionEntry.from_dict(v)
        for v in sorted(by_root.values(), key=lambda x: (x.get("char_start") or 0, x.get("section_root_id") or ""))
        if (
            str(v.get("section_title") or "").strip()
            or str(v.get("section_number") or "").strip()
            or str(v.get("section_label") or "").strip()
        )
    ]
    outline = _entries_with_appendix_propagation(raw_entries)
    def_roots: List[str] = []
    for entry in outline:
        blob = f"{entry.section_title} {entry.section_label}".strip()
        if blob and _DEFINITION_TITLE_RE.search(blob):
            def_roots.append(entry.section_root_id)
    return outline, def_roots


def compute_index_fingerprint(chunks: Sequence[Document]) -> str:
    version = ""
    for doc in chunks or []:
        md = doc.metadata or {}
        version = str(md.get("chunking_contract_version") or "").strip()
        if version:
            break
    count = len(chunks or [])
    digest = hashlib.sha256(f"{version}:{count}".encode("utf-8")).hexdigest()[:16]
    return f"{version or 'legacy'}:{count}:{digest}"


def outline_payload_from_chunks(chunks: Sequence[Document]) -> Dict[str, Any]:
    outline, def_roots = build_outline_from_chunks(chunks)
    return {
        "outline": [e.to_dict() for e in outline],
        "definition_section_roots": def_roots,
        "index_fingerprint": compute_index_fingerprint(chunks),
    }


def persist_outline_on_file(file_model: Any, payload: Dict[str, Any]) -> None:
    """Store outline JSON on File.processing_progress (survives ready state)."""
    from app.services.ingest_progress import apply_processing_progress

    apply_processing_progress(file_model, {OUTLINE_PAYLOAD_KEY: payload})


def load_outline_payload_from_file(file_model: Any) -> Optional[Dict[str, Any]]:
    progress = getattr(file_model, "processing_progress", None)
    if not isinstance(progress, dict):
        return None
    raw = progress.get(OUTLINE_PAYLOAD_KEY)
    return raw if isinstance(raw, dict) else None


def load_outline_from_vector_store(vector_store: Any, case_id: str, file_id: str) -> Dict[str, Any]:
    chunks = vector_store.list_chunks_by_file(case_id, file_id) if vector_store else []
    return outline_payload_from_chunks(chunks)
