"""Lightweight File queries for tabular review (no PDF blobs)."""
from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Query, Session, load_only

from app.models.case import File

# Table grid: names/types only — no text blobs, no file_content.
_TABLE_FILE_ATTRS = (
    File.id,
    File.case_id,
    File.filename,
    File.file_type,
    File.folder_id,
    File.processing_status,
    File.created_at,
)

# Cell extraction: id + text fallback; vectors via RAG by file_id — never file_content.
_EXTRACTION_FILE_ATTRS = (
    File.id,
    File.case_id,
    File.filename,
    File.file_type,
    File.original_text,
)


def _apply_load_only(query: Query, attrs: tuple) -> Query:
    return query.options(load_only(*attrs))


def query_files_for_table(
    db: Session,
    case_id: str,
    file_ids: Optional[List[str]] = None,
) -> Query:
    q = db.query(File).filter(File.case_id == case_id)
    if file_ids:
        q = q.filter(File.id.in_(file_ids))
    return _apply_load_only(q, _TABLE_FILE_ATTRS)


def fetch_files_for_table(
    db: Session,
    case_id: str,
    file_ids: Optional[List[str]] = None,
) -> List[File]:
    return query_files_for_table(db, case_id, file_ids).all()


def fetch_files_for_extraction(
    db: Session,
    case_id: str,
    file_ids: Optional[List[str]] = None,
) -> List[File]:
    q = db.query(File).filter(File.case_id == case_id)
    if file_ids:
        q = q.filter(File.id.in_(file_ids))
    return _apply_load_only(q, _EXTRACTION_FILE_ATTRS).all()


def fetch_files_ids_only(
    db: Session,
    case_id: str,
    file_ids: List[str],
) -> List[File]:
    """Existence check when creating a review — id (+ case_id) only."""
    return (
        db.query(File)
        .filter(File.case_id == case_id, File.id.in_(file_ids))
        .options(load_only(File.id, File.case_id))
        .all()
    )
