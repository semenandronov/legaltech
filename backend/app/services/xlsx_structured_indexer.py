"""
Index native Excel workbooks (.xlsx) as structured_table row chunks.

PDF statements go through Docling AST; Excel already is a grid — we parse it with
openpyxl and emit the same row Document contract used by CaseFileTransactionService.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.config import config
from app.services.structured_table_indexer import _INDEX_PROFILE, _format_row_content

logger = logging.getLogger(__name__)

_CONTRACT_VERSION = "structured-table-v1"
_PRESEG = "xlsx_openpyxl_grid"

_DATE_HEADER_RE = re.compile(r"(дата|date)", re.IGNORECASE)
_AMOUNT_HEADER_RE = re.compile(
    r"(сумм|amount|дебет|кредит|остаток|balance)",
    re.IGNORECASE,
)
_DESC_HEADER_RE = re.compile(
    r"(описан|назначен|description|purpose|контрагент|получател|плател)",
    re.IGNORECASE,
)


def is_excel_filename(filename: str) -> bool:
    name = (filename or "").lower().strip()
    return name.endswith(".xlsx") or name.endswith(".xlsm")


def try_index_xlsx_as_structured_table(
    *,
    content_bytes: bytes,
    filename: str,
    base_metadata: Dict[str, Any],
    doc_type: Optional[str] = None,
) -> Optional[List[Document]]:
    """
    Return structured_table Documents when the workbook looks like a register/statement.

    Returns None when Excel cannot be parsed or does not meet row/schema thresholds
    (caller should fall back to narrative indexing).
    """
    if not content_bytes or not is_excel_filename(filename):
        return None
    if not bool(getattr(config, "STRUCTURED_TABLE_INDEXING_ENABLED", True)):
        return None
    if not bool(getattr(config, "XLSX_STRUCTURED_TABLE_ENABLED", True)):
        return None

    try:
        sheets = _load_sheet_matrices(content_bytes)
    except Exception as exc:
        logger.warning("[xlsx_structured] failed to open %s: %s", filename, exc)
        return None

    min_rows = int(getattr(config, "STRUCTURED_TABLE_MIN_ROWS", 8) or 8)
    doc_id = str(base_metadata.get("doc_id") or base_metadata.get("file_id") or filename)
    all_docs: List[Document] = []
    global_row = 0

    for table_index, (sheet_name, matrix) in enumerate(sheets):
        header_idx, headers = _detect_header(matrix)
        if header_idx is None or not headers:
            continue
        data_rows = matrix[header_idx + 1 :]
        parsed: List[Dict[str, str]] = []
        for values in data_rows:
            row_columns = _align_row(headers, values)
            if not row_columns:
                continue
            if not any(str(v).strip() for v in row_columns.values()):
                continue
            parsed.append(row_columns)

        is_financial = _looks_like_financial_register(headers)
        force = _force_structured_doc_type(doc_type)
        # Bank-like sheets (date + amount headers): accept from 3 data rows.
        # Generic dense grids: require at least max(MIN_ROWS, 15).
        if not force:
            if is_financial:
                if len(parsed) < 3:
                    continue
            elif len(parsed) < max(min_rows, 15):
                continue

        for row_index, row_columns in enumerate(parsed):
            ordered_vals = [row_columns.get(h, "") for h in headers]
            body = _format_row_content(headers, ordered_vals)
            if not body.strip():
                continue
            md = _build_row_metadata(
                base_metadata=base_metadata,
                filename=filename,
                doc_id=doc_id,
                sheet_name=sheet_name,
                table_index=table_index,
                row_index=row_index,
                global_row_index=global_row,
                row_columns=row_columns,
            )
            all_docs.append(Document(page_content=body + "\n", metadata=md))
            global_row += 1

    if not all_docs:
        return None

    # Embedding prefix (same as StructuredTableIndexer).
    try:
        from app.services.legal_chunker import _apply_hidden_embedding_context

        _apply_hidden_embedding_context(
            all_docs,
            enabled=bool(getattr(config, "LEGAL_CHUNK_EMBED_PREFIX_ENABLED", True)),
        )
    except Exception:
        pass

    logger.info(
        "[xlsx_structured] %s → %s row chunks across %s sheet(s)",
        filename,
        len(all_docs),
        len({d.metadata.get("section_title") for d in all_docs}),
    )
    return all_docs


def _force_structured_doc_type(doc_type: Optional[str]) -> bool:
    normalized = str(doc_type or "").strip().lower()
    return normalized in {
        "bank_statement",
        "account_statement",
        "payment_register",
        "financial_register",
        "transaction_register",
    }


def _load_sheet_matrices(content_bytes: bytes) -> List[Tuple[str, List[List[Any]]]]:
    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(content_bytes), read_only=True, data_only=True)
    out: List[Tuple[str, List[List[Any]]]] = []
    try:
        for sheet in wb.worksheets:
            rows: List[List[Any]] = []
            for row in sheet.iter_rows(values_only=True):
                rows.append(list(row) if row else [])
            if rows:
                out.append((sheet.title or f"Sheet{len(out) + 1}", rows))
    finally:
        wb.close()
    return out


def _cell_str(value: Any) -> str:
    if value is None:
        return ""
    # openpyxl data_only returns datetime/date — format for RU statement parsers (DD.MM.YYYY).
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        # Amount parsers expect up to 2 fractional digits (RU bank statements).
        return f"{value:.2f}"
    text = str(value).strip()
    if text.lower() in ("none", "nan", "-"):
        return ""
    return text


def _detect_header(matrix: Sequence[Sequence[Any]]) -> Tuple[Optional[int], List[str]]:
    """Pick the first dense row; prefer rows with date/amount-like labels."""
    best: Tuple[Optional[int], List[str], float] = (None, [], -1.0)
    scan_limit = min(len(matrix), 40)
    for idx in range(scan_limit):
        raw = [_cell_str(c) for c in matrix[idx]]
        nonempty = [c for c in raw if c]
        if len(nonempty) < 2:
            continue
        headers: List[str] = []
        seen: Dict[str, int] = {}
        for j, cell in enumerate(raw):
            label = cell or f"Колонка{j + 1}"
            if label in seen:
                seen[label] += 1
                label = f"{label}_{seen[label]}"
            else:
                seen[label] = 1
            headers.append(label)
        score = float(len(nonempty))
        joined = " ".join(headers)
        if _DATE_HEADER_RE.search(joined):
            score += 5
        if _AMOUNT_HEADER_RE.search(joined):
            score += 5
        if _DESC_HEADER_RE.search(joined):
            score += 3
        if score > best[2]:
            best = (idx, headers, score)
    return best[0], best[1]


def _align_row(headers: Sequence[str], values: Sequence[Any]) -> Dict[str, str]:
    row_columns: Dict[str, str] = {}
    for i, header in enumerate(headers):
        val = _cell_str(values[i]) if i < len(values) else ""
        if val:
            row_columns[str(header)] = val
    return row_columns


def _looks_like_financial_register(headers: Sequence[str]) -> bool:
    joined = " ".join(headers)
    has_date = bool(_DATE_HEADER_RE.search(joined))
    has_amount = bool(_AMOUNT_HEADER_RE.search(joined))
    return has_date and has_amount


def _build_row_metadata(
    *,
    base_metadata: Dict[str, Any],
    filename: str,
    doc_id: str,
    sheet_name: str,
    table_index: int,
    row_index: int,
    global_row_index: int,
    row_columns: Dict[str, str],
) -> Dict[str, Any]:
    md: Dict[str, Any] = dict(base_metadata)
    md["source_file"] = filename
    md["doc_id"] = doc_id
    md["chunk_level"] = "row"
    md["chunk_profile"] = _INDEX_PROFILE
    md["index_profile"] = _INDEX_PROFILE
    md["chunking_contract_version"] = _CONTRACT_VERSION
    md["preseg_strategy"] = _PRESEG
    md["section_title"] = sheet_name
    md["section_number"] = ""
    md["parent_path"] = [sheet_name]
    md["clause_type"] = ""
    md["cross_references"] = []
    md["macro_id"] = ""
    md["parent_macro_id"] = ""
    md["is_table_fragment"] = False
    md["is_table_row"] = True
    md["table_index"] = int(table_index)
    md["row_index"] = int(row_index)
    md["global_row_index"] = int(global_row_index)
    md["row_columns"] = dict(row_columns)
    md["schema_quality"] = 1.0
    # Sheet index as synthetic "page" for UI navigation (1-based).
    md["page_start"] = int(table_index) + 1
    md["page_end"] = int(table_index) + 1
    # Stable chunk id
    raw = f"{doc_id}|xlsx-row|{table_index}|{row_index}|{global_row_index}"
    md["chunk_id"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]
    return md
