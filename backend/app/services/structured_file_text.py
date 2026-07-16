"""Build and load full structured source text for case files (editor paperclip)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.config import config

logger = logging.getLogger(__name__)

_PLAIN_JOIN_RE = re.compile(r"\n{3,}")

# CITATION_CONTRACT for structured_table / statement rows:
# original_text == STRUCTURED_ROW_SEPARATOR.join(normalized row bodies)
# and each row's char_start/char_end are offsets into that string.
STRUCTURED_ROW_SEPARATOR = "\n\n"


def normalize_structured_row_body(text: str) -> str:
    return (text or "").replace("\x00", "").strip()


def join_structured_row_bodies(bodies: Sequence[str]) -> str:
    parts = [normalize_structured_row_body(b) for b in bodies]
    parts = [p for p in parts if p]
    return STRUCTURED_ROW_SEPARATOR.join(parts)


def structured_row_char_spans(bodies: Sequence[str]) -> List[Tuple[str, int, int]]:
    """
    Return (normalized_body, char_start, char_end) for each non-empty body,
    consistent with join_structured_row_bodies().
    """
    out: List[Tuple[str, int, int]] = []
    offset = 0
    first = True
    for raw in bodies:
        body = normalize_structured_row_body(raw)
        if not body:
            continue
        if not first:
            offset += len(STRUCTURED_ROW_SEPARATOR)
        first = False
        start = offset
        end = start + len(body)
        out.append((body, start, end))
        offset = end
    return out


def _is_structured_table_row_document(doc: Document) -> bool:
    md = doc.metadata or {}
    if str(md.get("chunk_level") or "").strip() != "row":
        return False
    profile = str(md.get("index_profile") or "").strip()
    preseg = str(md.get("preseg_strategy") or "").strip()
    return profile == "structured_table" or preseg in {
        "xlsx_openpyxl_grid",
        "statement_geometry_native",
    }


def align_structured_table_row_stream(
    documents: Sequence[Document],
) -> Tuple[List[Document], Optional[str]]:
    """
    Rewrite structured row docs so char spans match the canonical original_text join.

    Non-row documents are left unchanged. Returns (all_docs, joined_row_text_or_none).
    """
    docs = list(documents or [])
    row_indices = [i for i, d in enumerate(docs) if _is_structured_table_row_document(d)]
    if not row_indices:
        return docs, None

    raw_bodies = [docs[i].page_content or "" for i in row_indices]
    spanned = structured_row_char_spans(raw_bodies)
    if len(spanned) != len(row_indices):
        # Empty bodies dropped — rebuild index map from non-empty only.
        keep: List[int] = []
        for idx, raw in zip(row_indices, raw_bodies):
            if normalize_structured_row_body(raw):
                keep.append(idx)
        row_indices = keep
        if len(spanned) != len(row_indices):
            logger.warning(
                "[structured_row_stream] span/body mismatch (%s vs %s); skipping align",
                len(spanned),
                len(row_indices),
            )
            return docs, join_structured_row_bodies(raw_bodies) or None

    joined = join_structured_row_bodies([body for body, _s, _e in spanned])
    for idx, (body, start, end) in zip(row_indices, spanned):
        src = docs[idx]
        md = dict(src.metadata or {})
        md["char_start"] = int(start)
        md["char_end"] = int(end)
        md["char_basis"] = "structured_row_stream"
        docs[idx] = Document(page_content=body, metadata=md)
    return docs, joined or None


def structured_text_from_indexed_documents(documents: List[Document]) -> Tuple[str, str]:
    """
    Reconstruct readable structured text from LegalChunkerV2 macro chunks (post-index).
    """
    if not documents:
        return "", "plain"

    macros = [
        d
        for d in documents
        if (d.metadata or {}).get("chunk_level") == "macro"
    ]
    if not macros:
        docling = [
            d for d in documents if (d.metadata or {}).get("chunk_level") == "docling"
        ]
        if docling:
            parts = [str(d.page_content or "").strip() for d in docling if d.page_content]
            joined = "\n\n".join(p for p in parts if p)
            return joined, "docling_direct"

        parts = [str(d.page_content or "").strip() for d in documents if d.page_content]
        joined = "\n\n".join(p for p in parts if p)
        return joined, "plain"

    macros.sort(key=lambda d: int((d.metadata or {}).get("char_start") or 0))

    blocks: List[str] = []
    last_title = ""
    for doc in macros:
        meta = doc.metadata or {}
        title = str(meta.get("section_title") or "").strip()
        body = str(doc.page_content or "").strip()
        if not body and not title:
            continue
        if title and title != last_title:
            blocks.append(f"## {title}")
            last_title = title
        if body:
            blocks.append(body)

    text = "\n\n".join(blocks).strip()
    return text, "markdown"


def normalize_structured_fallback(text: str) -> Tuple[str, str]:
    """Plain loader/OCR text with paragraph breaks preserved."""
    raw = (text or "").replace("\x00", "")
    raw = _PLAIN_JOIN_RE.sub("\n\n", raw)
    return raw.strip(), "plain"


def cap_structured_text(text: str, max_chars: int) -> str:
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text or ""
    note = f"\n\n[... документ обрезан до {max_chars} символов ...]\n"
    keep = max(0, max_chars - len(note))
    return (text[:keep] + note).strip()


def persist_structured_text_on_file(
    file_model: Any,
    documents: List[Document],
    *,
    fallback_text: str,
) -> None:
    """Set structured_text on File ORM row after indexing."""
    max_store = max(
        1000,
        int(getattr(config, "FILE_STRUCTURED_TEXT_MAX_STORE_CHARS", 2_000_000) or 2_000_000),
    )
    structured, fmt = structured_text_from_indexed_documents(documents)
    if not structured.strip():
        structured, fmt = normalize_structured_fallback(fallback_text)
    structured = cap_structured_text(structured, max_store)
    file_model.structured_text = structured or None
    file_model.structured_text_format = fmt if structured else None


def load_file_structured_text(file_row: Any) -> Tuple[str, str]:
    """Prefer structured_text, else original_text."""
    st = str(getattr(file_row, "structured_text", None) or "").strip()
    if st:
        return st, str(getattr(file_row, "structured_text_format", None) or "markdown")
    ot = str(getattr(file_row, "original_text", None) or "").strip()
    return ot, "plain"


def build_editor_attached_files_context(
    db: Session,
    *,
    case_id: str,
    user_id: str,
    file_ids: Sequence[str],
) -> str:
    """
    Full-text blocks for editor chat (no RAG). Validates case ownership and caps size.
    """
    from app.models.case import Case, File as CaseFile

    max_files = max(1, int(getattr(config, "EDITOR_ATTACH_MAX_FILES", 3) or 3))
    per_file_cap = max(
        1000,
        int(getattr(config, "EDITOR_ATTACH_MAX_CHARS_PER_FILE", 80_000) or 80_000),
    )
    total_cap = max(
        per_file_cap,
        int(getattr(config, "EDITOR_ATTACH_MAX_CHARS_TOTAL", 120_000) or 120_000),
    )

    ids = [str(x).strip() for x in file_ids if str(x).strip()][:max_files]
    if not ids or not case_id:
        return ""

    case = (
        db.query(Case)
        .filter(Case.id == case_id, Case.user_id == user_id)
        .first()
    )
    if not case:
        return ""

    rows = (
        db.query(CaseFile)
        .filter(CaseFile.case_id == case_id, CaseFile.id.in_(ids))
        .all()
    )
    by_id = {str(f.id): f for f in rows}
    blocks: List[str] = []
    total = 0

    for fid in ids:
        f = by_id.get(fid)
        if not f:
            continue
        body, fmt = load_file_structured_text(f)
        if not body:
            continue
        remaining_total = total_cap - total
        if remaining_total <= 0:
            break
        cap = min(per_file_cap, remaining_total)
        body = cap_structured_text(body, cap)
        if not body:
            continue
        fname = str(f.filename or fid)
        blocks.append(
            f"=== ПРИКРЕПЛЁННЫЙ ДОКУМЕНТ: {fname} (file_id={fid}, format={fmt}) ===\n"
            f"<context>\n{body}\n</context>"
        )
        total += len(body)

    return "\n\n".join(blocks)
