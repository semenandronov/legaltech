"""Document Context Package (DCP) for tabular review runs."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.config import config
from app.models.case import File
from app.services.file_document_outline import (
    OutlineSectionEntry,
    load_outline_from_vector_store,
    load_outline_payload_from_file,
    outline_payload_from_chunks,
)

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_file_context_cache: Dict[Tuple[str, str, str], "TabularFileContextPackage"] = {}


def tabular_dcp_enabled() -> bool:
    return bool(getattr(config, "TABULAR_DCP_ENABLED", True))


@dataclass(frozen=True)
class TabularFileContextPackage:
    file_id: str
    outline: Tuple[OutlineSectionEntry, ...]
    passport_blurb: str
    definition_section_roots: Tuple[str, ...]
    index_fingerprint: str

    def outline_titles_for_router(self, limit: int = 40) -> List[Tuple[str, str, str]]:
        """(section_root_id, title, label) for routing."""
        rows: List[Tuple[str, str, str]] = []
        for entry in self.outline[:limit]:
            title = entry.section_title or entry.section_number or entry.section_root_id
            label = entry.section_label or title
            rows.append((entry.section_root_id, title, label))
        return rows


def _passport_blurb(file_row: File) -> str:
    parts: List[str] = []
    summary = str(getattr(file_row, "doc_summary_short", None) or "").strip()
    if summary:
        parts.append(summary)
    kp = getattr(file_row, "doc_key_points", None)
    if isinstance(kp, list):
        for item in kp[:8]:
            s = str(item).strip()
            if s:
                parts.append(f"- {s}")
    return "\n".join(parts)[:4000]


def build_file_context_package(
    *,
    file_row: File,
    outline_payload: Dict[str, Any],
) -> TabularFileContextPackage:
    outline_raw = outline_payload.get("outline") or []
    outline = tuple(
        OutlineSectionEntry.from_dict(x)
        for x in outline_raw
        if isinstance(x, dict)
        and (
            str(x.get("section_title") or "").strip()
            or str(x.get("section_number") or "").strip()
            or str(x.get("section_label") or "").strip()
        )
    )
    def_roots = tuple(
        str(x).strip()
        for x in (outline_payload.get("definition_section_roots") or [])
        if str(x).strip()
    )
    fingerprint = str(outline_payload.get("index_fingerprint") or "unknown")
    return TabularFileContextPackage(
        file_id=str(file_row.id),
        outline=outline,
        passport_blurb=_passport_blurb(file_row),
        definition_section_roots=def_roots,
        index_fingerprint=fingerprint,
    )


def resolve_file_context_package(
    db: Session,
    *,
    case_id: str,
    file_row: File,
    vector_store: Any = None,
) -> TabularFileContextPackage:
    fid = str(file_row.id)
    persisted = load_outline_payload_from_file(file_row)
    if persisted and persisted.get("outline"):
        pkg = build_file_context_package(file_row=file_row, outline_payload=persisted)
    else:
        if vector_store is None:
            from app.services.document_processor import get_document_processor

            vector_store = getattr(get_document_processor(), "vector_store", None)
        payload = load_outline_from_vector_store(vector_store, case_id, fid)
        pkg = build_file_context_package(file_row=file_row, outline_payload=payload)

    if tabular_dcp_enabled():
        key = (str(case_id), fid, pkg.index_fingerprint)
        with _cache_lock:
            _file_context_cache[key] = pkg
    return pkg


def prepare_file_context_packages(
    db: Session,
    *,
    case_id: str,
    file_ids: Sequence[str],
    vector_store: Any = None,
) -> Dict[str, TabularFileContextPackage]:
    if not file_ids:
        return {}
    rows = (
        db.query(File)
        .filter(File.case_id == str(case_id), File.id.in_([str(x) for x in file_ids]))
        .all()
    )
    out: Dict[str, TabularFileContextPackage] = {}
    for row in rows:
        try:
            out[str(row.id)] = resolve_file_context_package(
                db, case_id=case_id, file_row=row, vector_store=vector_store
            )
        except Exception as exc:
            logger.warning("DCP build failed file=%s: %s", row.id, exc)
    return out
