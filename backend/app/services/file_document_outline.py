"""Persisted document outline (section_root map) for tabular context engineering."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_root_id": self.section_root_id,
            "section_title": self.section_title,
            "section_number": self.section_number,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "section_label": self.section_label,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "OutlineSectionEntry":
        return cls(
            section_root_id=str(raw.get("section_root_id") or "").strip(),
            section_title=str(raw.get("section_title") or "").strip(),
            section_number=str(raw.get("section_number") or "").strip(),
            char_start=int(raw.get("char_start") or 0),
            char_end=int(raw.get("char_end") or 0),
            section_label=str(raw.get("section_label") or "").strip(),
        )


def _int_meta(md: Dict[str, Any], key: str) -> int:
    try:
        return int(md.get(key) or 0)
    except (TypeError, ValueError):
        return 0


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
        row = by_root.get(sid)
        if row is None:
            by_root[sid] = {
                "section_root_id": sid,
                "section_title": title,
                "section_number": num,
                "char_start": cs,
                "char_end": ce,
                "section_label": label,
            }
            continue
        if cs and cs < int(row.get("char_start") or 0) or not row.get("char_start"):
            row["char_start"] = cs
            if title:
                row["section_title"] = title
            if num:
                row["section_number"] = num
        if ce > int(row.get("char_end") or 0):
            row["char_end"] = ce
        if label and not row.get("section_label"):
            row["section_label"] = label

    outline = [
        OutlineSectionEntry.from_dict(v)
        for v in sorted(by_root.values(), key=lambda x: (x.get("char_start") or 0, x.get("section_root_id") or ""))
    ]
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
