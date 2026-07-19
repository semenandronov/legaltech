"""
Index digital PDF statements via native table extract, then geometry fallback.

Order of preference (digital PDF with text layer only):
1. Native tables — PyMuPDF find_tables / Camelot, columns mapped by header labels
2. Geometry snap — last resort when native strategies fail quality gates

Gate: only when the system decides the document is a statement/register
(doc_type in structured set OR columnar register probe). OCR/scans stay on
the Docling path.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.chunk_ids import generate_chunk_id
from app.services.document_structure_classifier import STRUCTURED_DOC_TYPES
from app.services.statement_geometry_extractor import (
    extract_statement_operations,
    operations_to_matrix,
    probe_register_likelihood,
)
from app.services.statement_native_table_extract import (
    extract_best_native_statement_table,
    result_to_canonical_matrix,
)
from app.services.structured_file_text import (
    align_structured_table_row_stream,
    normalize_structured_row_body,
)
from app.services.structured_table_indexer import (
    _CONTRACT_VERSION,
    _INDEX_PROFILE,
    _format_row_content,
)
from app.services.table_schema_normalize import (
    ColumnRole,
    assess_operation_row_quality,
    normalize_amount_cell,
)

logger = logging.getLogger(__name__)

_PRESEG_NATIVE = "statement_native_table"
_PRESEG_GEOMETRY = "statement_geometry_native"


def geometry_statement_indexing_enabled() -> bool:
    if not bool(getattr(config, "STRUCTURED_TABLE_INDEXING_ENABLED", True)):
        return False
    return bool(getattr(config, "STATEMENT_GEOMETRY_INDEXING_ENABLED", True))


def should_try_statement_geometry(
    *,
    filename: str,
    doc_type: Optional[str],
    loader_native_text: bool,
    loader_did_ocr: bool,
    content_bytes: Optional[bytes],
) -> bool:
    """
    Hard gate before geometry/native statement path.

    Never runs on OCR/scans. Requires PDF + native text + (typed statement OR probe).
    """
    if not geometry_statement_indexing_enabled():
        return False
    if loader_did_ocr:
        return False
    if not loader_native_text:
        return False
    if not content_bytes:
        return False
    name = (filename or "").lower().strip()
    if not name.endswith(".pdf"):
        return False

    normalized = str(doc_type or "").strip().lower()
    if normalized in STRUCTURED_DOC_TYPES:
        return True

    is_reg, conf, reason = probe_register_likelihood(content_bytes)
    logger.info(
        "[statement_geometry] probe file=%s register=%s conf=%.2f reason=%s",
        filename,
        is_reg,
        conf,
        reason,
    )
    return bool(is_reg)


def _quality_accept(
    *,
    row_count: int,
    with_amount: int,
    with_date: int,
) -> Optional[str]:
    """Return rejection code or None when quality is acceptable."""
    min_rows = int(getattr(config, "STRUCTURED_TABLE_MIN_ROWS", 8) or 8)
    min_amount_ratio = float(
        getattr(config, "STATEMENT_GEOMETRY_MIN_AMOUNT_RATIO", 0.85) or 0.85
    )
    min_date_ratio = float(
        getattr(config, "STATEMENT_GEOMETRY_MIN_DATE_RATIO", 0.90) or 0.90
    )
    if row_count < min_rows:
        return f"too_few_rows:{row_count}<{min_rows}"
    if row_count <= 0:
        return "empty"
    amount_ratio = with_amount / row_count
    date_ratio = with_date / row_count
    if amount_ratio < min_amount_ratio:
        return f"low_amount_ratio:{amount_ratio:.2f}"
    if date_ratio < min_date_ratio:
        return f"low_date_ratio:{date_ratio:.2f}"
    return None


def _matrix_quality_stats(
    matrix: Sequence[Sequence[str]],
    roles: Optional[Sequence[str]] = None,
) -> Tuple[int, int, int]:
    """Count rows with a non-empty primary amount / date cell."""
    role_list = list(roles or [])
    amount_idxs = [
        i for i, r in enumerate(role_list) if str(r) == ColumnRole.AMOUNT.value
    ]
    date_idxs = [
        i for i, r in enumerate(role_list) if str(r) == ColumnRole.DATE.value
    ]
    # Legacy compact matrix: date at 0, amount at 2.
    if not amount_idxs and matrix and len(matrix[0]) > 2:
        amount_idxs = [2]
    if not date_idxs:
        date_idxs = [0]

    with_amount = 0
    with_date = 0
    for row in matrix:
        if any((row[i] if i < len(row) else "").strip() for i in amount_idxs):
            with_amount += 1
        if any((row[i] if i < len(row) else "").strip() for i in date_idxs):
            with_date += 1
    return len(matrix), with_amount, with_date


def _primary_amount_header(headers: Sequence[str], roles: Sequence[str]) -> str:
    for header, role in zip(headers, roles):
        if str(role) == ColumnRole.AMOUNT.value:
            return str(header)
    return ""


def _try_native_path(
    *,
    content_bytes: bytes,
    filename: str,
    base_metadata: Dict[str, Any],
) -> Optional[List[Document]]:
    if not bool(getattr(config, "STATEMENT_NATIVE_TABLE_EXTRACT_ENABLED", True)):
        return None

    enable_camelot = bool(getattr(config, "STATEMENT_CAMELOT_ENABLED", True))
    min_score = float(getattr(config, "STATEMENT_NATIVE_MIN_SCORE", 55) or 55)
    native = extract_best_native_statement_table(
        content_bytes,
        enable_camelot=enable_camelot,
        min_score=min_score,
    )
    if native is None or not native.rows:
        return None

    headers, matrix, roles = result_to_canonical_matrix(native)
    row_count, with_amount, with_date = _matrix_quality_stats(matrix, roles)
    reject = _quality_accept(
        row_count=row_count,
        with_amount=with_amount,
        with_date=with_date,
    )
    if reject:
        logger.info(
            "[statement_native] quality reject %s strategy=%s: %s "
            "(rows=%s amount=%s/%s date=%s/%s score=%.1f)",
            filename,
            native.strategy,
            reject,
            row_count,
            with_amount,
            row_count,
            with_date,
            row_count,
            native.score,
        )
        return None

    pages = [row.page for row in native.rows]
    docs = _rows_to_documents(
        headers=headers,
        matrix=matrix,
        roles=roles,
        pages=pages,
        filename=filename,
        base_metadata=base_metadata,
        preseg_strategy=_PRESEG_NATIVE,
        extract_strategy=native.strategy,
        extract_score=native.score,
        primary_amount_header=_primary_amount_header(headers, roles)
        or native.primary_amount_header,
    )
    logger.info(
        "[statement_native] %s → structured_table rows=%s strategy=%s score=%.1f",
        filename,
        len(docs),
        native.strategy,
        native.score,
    )
    return docs


def _try_geometry_path(
    *,
    content_bytes: bytes,
    filename: str,
    base_metadata: Dict[str, Any],
) -> Optional[List[Document]]:
    max_pages = int(getattr(config, "DOCLING_MAX_PAGES_PER_DOC", 2000) or 2000)
    result = extract_statement_operations(content_bytes, max_pages=max_pages)
    if not result.operations:
        logger.info(
            "[statement_geometry] reject %s: %s",
            filename,
            result.rejection or "no_operations",
        )
        return None

    headers, matrix, roles = operations_to_matrix(result)
    row_count, with_amount, with_date = _matrix_quality_stats(matrix, roles)
    reject = _quality_accept(
        row_count=row_count,
        with_amount=with_amount,
        with_date=with_date,
    )
    if reject:
        logger.info(
            "[statement_geometry] quality reject %s: %s (rows=%s amount=%s/%s date=%s/%s)",
            filename,
            reject,
            row_count,
            with_amount,
            row_count,
            with_date,
            row_count,
        )
        return None

    pages = [op.page for op in result.operations]
    docs = _rows_to_documents(
        headers=headers,
        matrix=matrix,
        roles=roles,
        pages=pages,
        filename=filename,
        base_metadata=base_metadata,
        preseg_strategy=_PRESEG_GEOMETRY,
        extract_strategy="geometry",
        extract_score=None,
        primary_amount_header=_primary_amount_header(headers, roles),
    )
    logger.info(
        "[statement_geometry] %s → structured_table rows=%s pages=%s preseg=%s",
        filename,
        len(docs),
        result.pages_scanned,
        _PRESEG_GEOMETRY,
    )
    return docs


def try_index_pdf_as_statement_geometry(
    *,
    content_bytes: bytes,
    filename: str,
    base_metadata: Dict[str, Any],
    doc_type: Optional[str] = None,
) -> Optional[List[Document]]:
    """
    Extract operations and emit structured_table row Documents.

    Prefers native table strategies; falls back to geometry snap.
    Returns None when both fail — caller falls back to Docling.
    """
    if not content_bytes:
        return None

    native_docs = _try_native_path(
        content_bytes=content_bytes,
        filename=filename,
        base_metadata=base_metadata,
    )
    if native_docs:
        return native_docs

    return _try_geometry_path(
        content_bytes=content_bytes,
        filename=filename,
        base_metadata=base_metadata,
    )


def _rows_to_documents(
    *,
    headers: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[str],
    pages: Sequence[int],
    filename: str,
    base_metadata: Dict[str, Any],
    preseg_strategy: str = _PRESEG_GEOMETRY,
    extract_strategy: Optional[str] = None,
    extract_score: Optional[float] = None,
    primary_amount_header: Optional[str] = None,
) -> List[Document]:
    md_base = dict(base_metadata or {})
    doc_id = str(md_base.get("doc_id") or md_base.get("file_id") or filename)
    draft: List[Document] = []
    primary_header = (primary_amount_header or "").strip() or _primary_amount_header(
        headers, roles
    )

    for global_row_index, values in enumerate(matrix):
        row_columns: Dict[str, str] = {}
        for idx, header in enumerate(headers):
            raw = values[idx] if idx < len(values) else ""
            cell = str(raw or "").strip()
            role = roles[idx] if idx < len(roles) else ""
            if role == ColumnRole.AMOUNT.value and cell:
                cell = normalize_amount_cell(cell) or cell
            if role == ColumnRole.BALANCE.value and cell:
                cell = normalize_amount_cell(cell) or cell
            row_columns[str(header)] = cell

        if not any(str(v).strip() for v in row_columns.values()):
            continue

        ordered_vals = [row_columns.get(h, "") for h in headers]
        body = normalize_structured_row_body(
            _format_row_content(list(headers), ordered_vals)
        )
        if not body:
            continue
        md: Dict[str, Any] = dict(md_base)
        md.update(
            {
                "source_file": filename,
                "doc_id": doc_id,
                "chunk_level": "row",
                "chunk_profile": _INDEX_PROFILE,
                "index_profile": _INDEX_PROFILE,
                "chunking_contract_version": _CONTRACT_VERSION,
                "preseg_strategy": preseg_strategy,
                "hybrid_file_profile": _INDEX_PROFILE,
                "section_title": "",
                "section_number": "",
                "parent_path": [],
                "clause_type": "",
                "cross_references": [],
                "macro_id": "",
                "parent_macro_id": "",
                "is_table_fragment": False,
                "is_table_row": True,
                "table_index": 0,
                "row_index": int(global_row_index),
                "global_row_index": int(global_row_index),
                "row_columns": row_columns,
                "column_roles": list(roles),
                "column_headers": list(headers),
                "schema_quality": 1.0,
                "chunk_index": int(global_row_index),
                # Placeholder; align_structured_table_row_stream sets final offsets.
                "char_start": 0,
                "char_end": 0,
                "chunk_id": generate_chunk_id(doc_id, global_row_index, 0),
            }
        )
        if primary_header:
            md["primary_amount_header"] = primary_header
        if extract_strategy:
            md["statement_extract_strategy"] = extract_strategy
        if extract_score is not None:
            md["statement_extract_score"] = float(extract_score)
        if global_row_index < len(pages) and pages[global_row_index]:
            md["page_start"] = int(pages[global_row_index])
        score, warnings = assess_operation_row_quality(
            row_columns,
            column_roles=roles,
        )
        md["row_quality"] = float(score)
        if warnings:
            md["row_quality_warnings"] = list(warnings)

        draft.append(Document(page_content=body, metadata=md))

    aligned, _joined = align_structured_table_row_stream(draft)
    for doc in aligned:
        md = doc.metadata or {}
        md["chunk_id"] = generate_chunk_id(
            doc_id,
            int(md.get("global_row_index") or 0),
            int(md.get("char_start") or 0),
        )
    return aligned
