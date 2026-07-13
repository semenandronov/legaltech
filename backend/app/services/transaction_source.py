"""Row-level PDF source contract for bank statement transactions (CITATION_CONTRACT_V1)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document

from app.services.rag_service import RAGService

_MIN_HIGHLIGHT_FRAGMENT_LEN = 4
_WS_RE = re.compile(r"\s+")
_LABELED_LINE_RE = re.compile(r"^([^:\n]{1,80}):\s+(.+)$")
_DESC_KEY_RE = re.compile(
    r"(описан|назначен|description|purpose|контрагент|получател|плател)",
    re.IGNORECASE,
)
_AMOUNT_KEY_RE = re.compile(
    r"(сумм|amount|дебет|кредит|остаток|balance)",
    re.IGNORECASE,
)
_DATE_KEY_RE = re.compile(r"(дата|date)", re.IGNORECASE)


def build_verbatim_row_text(
    row_columns: Dict[str, str],
    *,
    page_content: Optional[str] = None,
    column_order: Optional[Sequence[str]] = None,
) -> str:
    """Canonical row text for PDF highlight and audit trail."""
    content = (page_content or "").strip()
    if content:
        return content

    if not row_columns:
        return ""

    keys: List[str]
    if column_order:
        keys = [k for k in column_order if k in row_columns]
        keys.extend(k for k in row_columns if k not in keys)
    else:
        keys = list(row_columns.keys())

    parts: List[str] = []
    for key in keys:
        value = str(row_columns.get(key) or "").strip()
        if value:
            parts.append(value)
    return " | ".join(parts) if parts else ""


def _cell_values_by_priority(row_columns: Dict[str, str]) -> List[str]:
    """Order cell values for DOM/HTML matching: description → other → amount → date."""
    desc: List[str] = []
    amounts: List[str] = []
    dates: List[str] = []
    other: List[str] = []
    for key, raw in row_columns.items():
        value = _WS_RE.sub(" ", str(raw or "").strip())
        if not value:
            continue
        label = key or ""
        if _DESC_KEY_RE.search(label):
            desc.append(value)
        elif _AMOUNT_KEY_RE.search(label):
            amounts.append(value)
        elif _DATE_KEY_RE.search(label):
            dates.append(value)
        else:
            other.append(value)

    ordered: List[str] = []
    for group in (desc, other, amounts, dates):
        ordered.extend(sorted(group, key=len, reverse=True))
    return ordered


def _values_from_labeled_verbatim(verbatim_row_text: str) -> List[str]:
    """Parse 'Col: value' chunk lines into bare cell values (Excel/HTML table text)."""
    values: List[str] = []
    for line in (verbatim_row_text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _LABELED_LINE_RE.match(stripped)
        if match:
            values.append(_WS_RE.sub(" ", match.group(2).strip()))
        else:
            values.append(_WS_RE.sub(" ", stripped))
    return values


def build_highlight_fragments(
    row_columns: Dict[str, str],
    *,
    verbatim_row_text: str,
) -> List[str]:
    """
    Ordered candidates for viewer highlight (PDF text-layer + HTML table preview).

    Prefer bare cell values (what appears in Excel/HTML cells). Keep full verbatim
    last — it matches PDF rows that retain "Col: value" labels, but not HTML grids.
    """
    seen: set[str] = set()
    fragments: List[str] = []

    def add(raw: str) -> None:
        text = _WS_RE.sub(" ", (raw or "").strip())
        if len(text) < _MIN_HIGHLIGHT_FRAGMENT_LEN:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        fragments.append(text)

    columns = {
        str(k): str(v)
        for k, v in (row_columns or {}).items()
        if k is not None and v is not None and str(v).strip()
    }
    for value in _cell_values_by_priority(columns):
        add(value)

    if not columns:
        for value in _values_from_labeled_verbatim(verbatim_row_text):
            add(value)

    if len(columns) >= 2:
        joined = _WS_RE.sub(
            " ",
            " ".join(str(v).strip() for v in columns.values() if str(v).strip()),
        )
        add(joined)

    primary = _WS_RE.sub(" ", (verbatim_row_text or "").strip())
    if primary:
        add(primary)

    return fragments


def highlight_targets_from_row_metadata(
    metadata: Dict[str, Any],
    *,
    page_content: str = "",
) -> List[str]:
    """Build highlight_targets for structured_table / Excel row citation payloads."""
    md = metadata or {}
    if str(md.get("chunk_level") or "").strip() != "row":
        return []

    raw_columns = md.get("row_columns")
    columns: Dict[str, str] = {}
    if isinstance(raw_columns, dict):
        columns = {
            str(k): str(v)
            for k, v in raw_columns.items()
            if k is not None and v is not None and str(v).strip()
        }

    verbatim = (page_content or "").strip()
    if not verbatim:
        verbatim = build_verbatim_row_text(columns)

    return build_highlight_fragments(columns, verbatim_row_text=verbatim)


def _union_bbox(regions: Sequence[Dict[str, float]]) -> Optional[Dict[str, float]]:
    if not regions:
        return None
    x0 = min(r["x0"] for r in regions)
    y0 = min(r["y0"] for r in regions)
    x1 = max(r["x1"] for r in regions)
    y1 = max(r["y1"] for r in regions)
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1}


def build_source_references(
    *,
    verbatim_text: str,
    page_start: Optional[int],
    metadata: Dict[str, Any],
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build CITATION_CONTRACT_V1 source_references from indexed row chunk metadata."""
    regions, page_bbox = RAGService._extract_bbox_regions(
        metadata,
        char_start=char_start,
        char_end=char_end,
    )

    refs: List[Dict[str, Any]] = []
    text = (verbatim_text or "").strip()
    if not regions:
        if text or page_start is not None:
            refs.append(
                {
                    "page": page_start,
                    "section": None,
                    "text": text,
                }
            )
        return refs

    union = _union_bbox(regions)
    for idx, region in enumerate(regions):
        ref: Dict[str, Any] = {
            "page": page_start,
            "section": None,
            "text": text if idx == 0 else "",
            "bbox": region,
        }
        if page_bbox:
            ref["page_bbox"] = page_bbox
        refs.append(ref)

    if union and refs:
        refs[0]["bbox"] = union
    return refs


def extract_row_source_from_document(
    doc: Document,
    *,
    column_order: Optional[Sequence[str]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """verbatim_row_text + source_references from a structured-table row chunk."""
    md = doc.metadata or {}
    row_columns = md.get("row_columns")
    columns = (
        {str(k): str(v) for k, v in row_columns.items() if k and v is not None}
        if isinstance(row_columns, dict)
        else {}
    )

    verbatim = build_verbatim_row_text(
        columns,
        page_content=doc.page_content,
        column_order=column_order,
    )
    page_start = int(md["page_start"]) if md.get("page_start") is not None else None
    char_start = int(md["char_start"]) if md.get("char_start") is not None else None
    char_end = int(md["char_end"]) if md.get("char_end") is not None else None

    refs = build_source_references(
        verbatim_text=verbatim,
        page_start=page_start,
        metadata=md,
        char_start=char_start,
        char_end=char_end,
    )
    return verbatim, refs


def resolve_row_source_for_db_row(
    *,
    row_columns: Dict[str, str],
    verbatim_row_text: Optional[str],
    source_references: Optional[List[Dict[str, Any]]],
    page_start: Optional[int],
    char_start: Optional[int],
    char_end: Optional[int],
    description: Optional[str],
) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """API/runtime resolution when DB fields are partially populated (legacy rows)."""
    columns = {str(k): str(v) for k, v in (row_columns or {}).items() if k and v is not None}
    stored_verbatim = verbatim_row_text if isinstance(verbatim_row_text, str) else None
    verbatim = (stored_verbatim or "").strip() or build_verbatim_row_text(columns)
    refs = list(source_references or [])
    if not refs and (verbatim or page_start is not None):
        refs = [
            {
                "page": page_start,
                "section": None,
                "text": verbatim or (description or ""),
            }
        ]

    fragments = build_highlight_fragments(columns, verbatim_row_text=verbatim)
    if not fragments and description:
        fragments = build_highlight_fragments({}, verbatim_row_text=description)

    return verbatim, refs, fragments
