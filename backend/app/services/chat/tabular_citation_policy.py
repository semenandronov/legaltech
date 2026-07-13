"""
Policy for Excel / structured_table citations.

Production rule: cite operation rows only — never whole-sheet dumps from
loader OCR / original_text windows.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from langchain_core.documents import Document

_REGISTER_HEADER_MARKERS = (
    "номер карты",
    "дата списания",
    "описание операции",
    "сумма в валюте",
    "сумма операции",
    "дата и время операции",
)

_ORIGINAL_WINDOW_SOURCES = frozenset(
    {
        "original_window",
        "original_head",
        "original_tail",
    }
)

_DATE_LINE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
_WS_RE = re.compile(r"\s+")


def is_structured_row_metadata(metadata: Optional[Dict[str, Any]]) -> bool:
    md = metadata or {}
    if str(md.get("chunk_level") or "").strip().lower() != "row":
        return False
    if str(md.get("index_profile") or "").strip() == "structured_table":
        return True
    if md.get("is_table_row") is True:
        return True
    if isinstance(md.get("row_columns"), dict) and md.get("row_columns"):
        return True
    return False


def is_structured_row_document(doc: Document) -> bool:
    return is_structured_row_metadata(getattr(doc, "metadata", None) or {})


def inventory_is_structured_table_rows(chunks: Sequence[Document]) -> bool:
    """True when vector inventory is dominated by structured_table row chunks."""
    docs = [d for d in chunks if isinstance(d, Document)]
    if not docs:
        return False
    row_n = sum(1 for d in docs if is_structured_row_document(d))
    if row_n < 3:
        return False
    return row_n >= max(3, int(len(docs) * 0.5))


def within_file_source(metadata: Optional[Dict[str, Any]]) -> str:
    return str((metadata or {}).get("within_file_source") or "").strip()


def is_original_text_window_metadata(metadata: Optional[Dict[str, Any]]) -> bool:
    src = within_file_source(metadata)
    if src in _ORIGINAL_WINDOW_SOURCES:
        return True
    return src.startswith("original_")


def looks_like_multi_row_register_dump(text: str) -> bool:
    """
    Detect whole-sheet / multi-row register text (OCR grid or original_text window).

    Row chunks use ``Col: value`` lines and cover a single operation — they must not match.
    """
    raw = (text or "").strip()
    if len(raw) < 120:
        return False
    lowered = raw.casefold()
    header_hits = sum(1 for h in _REGISTER_HEADER_MARKERS if h in lowered)
    if header_hits < 2:
        return False
    date_hits = len(_DATE_LINE_RE.findall(raw))
    # One operation row usually has 1–3 date mentions; a sheet dump has many.
    if date_hits >= 4:
        return True
    # Grid-style dumps: many short lines (cell-per-line) plus headers.
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) >= 12 and header_hits >= 2:
        labeled = sum(1 for ln in lines if ":" in ln)
        # Structured row chunks are mostly "Col: value"; sheet grids are not.
        if labeled <= max(3, len(lines) // 4):
            return True
    return False


def file_ids_with_structured_rows(docs: Sequence[Document]) -> Set[str]:
    out: Set[str] = set()
    for doc in docs:
        if not is_structured_row_document(doc):
            continue
        md = doc.metadata or {}
        fid = str(md.get("file_id") or md.get("doc_id") or "").strip()
        if fid:
            out.add(fid)
    return out


def should_exclude_tabular_dump_document(
    doc: Document,
    *,
    structured_file_ids: Optional[Iterable[str]] = None,
) -> bool:
    """
    Drop whole-sheet evidence when the same file already has row chunks,
    or when the passage itself is a multi-row register dump without row metadata.
    """
    if is_structured_row_document(doc):
        return False
    md = doc.metadata or {}
    fid = str(md.get("file_id") or md.get("doc_id") or "").strip()
    structured_ids = {str(x) for x in (structured_file_ids or []) if str(x).strip()}
    text = str(getattr(doc, "page_content", "") or "")

    if fid and fid in structured_ids:
        if is_original_text_window_metadata(md):
            return True
        if looks_like_multi_row_register_dump(text):
            return True
        return False

    if looks_like_multi_row_register_dump(text) and not is_structured_row_metadata(md):
        return True
    return False


def filter_docs_for_tabular_citations(docs: Sequence[Document]) -> List[Document]:
    """Remove whole-sheet dumps before prompt numbering / citation SSE."""
    structured_ids = file_ids_with_structured_rows(docs)
    out: List[Document] = []
    for doc in docs:
        if should_exclude_tabular_dump_document(doc, structured_file_ids=structured_ids):
            continue
        out.append(doc)
    return out
