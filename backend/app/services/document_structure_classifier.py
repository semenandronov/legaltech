"""Classify Docling AST into narrative vs structured-table indexing strategies."""

from __future__ import annotations

import re
from typing import Literal, Sequence

from app.config import config
from app.services.legal_chunker import _Segment, _parse_markdown_pipe_table

IndexingStrategy = Literal["narrative", "structured_table"]

_STRUCTURED_DOC_TYPES = frozenset(
    {
        "bank_statement",
        "account_statement",
        "payment_register",
        "financial_register",
        "transaction_register",
    }
)

_FINANCIAL_HEADING_RE = re.compile(
    r"(движени[ея]\s+средств|выписк[аи]|справк[аи]\s+о\s+движении|"
    r"account\s+statement|bank\s+statement|transaction\s+history)",
    re.IGNORECASE,
)


def _count_table_data_rows(segment_text: str) -> int:
    parsed = _parse_markdown_pipe_table(segment_text or "")
    if not parsed:
        return 0
    _header, _sep, data = parsed
    return len(data)


def classify_indexing_strategy(
    segments: Sequence[_Segment],
    *,
    full_text: str,
    doc_type: str | None = None,
) -> IndexingStrategy:
    """
    Decide whether to index as structured table rows or narrative macro/micro.

    Uses Docling segment signals only — no filename heuristics.
    """
    if not bool(getattr(config, "STRUCTURED_TABLE_INDEXING_ENABLED", True)):
        return "narrative"

    normalized_doc_type = str(doc_type or "").strip().lower()
    if normalized_doc_type in _STRUCTURED_DOC_TYPES:
        return "structured_table"

    if not segments:
        return "narrative"

    table_segments = [s for s in segments if s.is_table]
    if not table_segments:
        return "narrative"

    total_chars = max(len(full_text or ""), 1)
    table_chars = sum(len(s.text or "") for s in table_segments)
    table_ratio = table_chars / total_chars

    min_ratio = float(
        getattr(config, "STRUCTURED_TABLE_MIN_CHAR_RATIO", 0.45) or 0.45
    )
    min_rows = int(getattr(config, "STRUCTURED_TABLE_MIN_ROWS", 8) or 8)
    min_tables = int(getattr(config, "STRUCTURED_TABLE_MIN_TABLE_SEGMENTS", 1) or 1)

    total_rows = sum(_count_table_data_rows(s.text) for s in table_segments)
    if len(table_segments) < min_tables or total_rows < min_rows:
        return "narrative"

    if table_ratio >= min_ratio:
        return "structured_table"

    # Mixed document: strong financial heading + meaningful table body.
    heading_hit = bool(_FINANCIAL_HEADING_RE.search(full_text or ""))
    if heading_hit and total_rows >= min_rows and table_ratio >= 0.30:
        return "structured_table"

    return "narrative"
