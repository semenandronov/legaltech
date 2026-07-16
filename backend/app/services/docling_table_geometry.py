"""
Geometry-aware Docling table extraction.

Docling TableItem.grid / export_to_markdown can merge adjacent visual columns
into one wide cell. Native PDF text still has separate X positions.

Contract:
  - prefer Docling grid as the row/column scaffold
  - when a column bbox is anomalously wide, split it using PDF word X-gaps
    (median split across data rows) — geometry only, no bank-specific labels
  - if PDF has no text layer, keep Docling grid unchanged
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Column wider than this × median sibling width is a split candidate.
_WIDE_COLUMN_RATIO = 1.75
# Minimum X gap (PDF points) inside a row to treat as a column boundary.
_MIN_ROW_GAP_PT = 14.0
# Need this many data rows agreeing on a gap before splitting.
_MIN_SPLIT_ROWS = 3


@dataclass(frozen=True)
class PdfWord:
    x: float
    y_bottom: float
    y_top: float
    text: str


@dataclass(frozen=True)
class GeometryTable:
    headers: List[str]
    rows: List[List[str]]
    source: str  # "docling_grid" | "docling_grid+pdf_geometry"


def extract_pdf_page_words(pdf_bytes: bytes, page_index: int) -> Tuple[List[PdfWord], float]:
    """
    Extract positioned words from one PDF page (0-based).

    Returns (words, page_height). Coordinates: x from left, y_top from top
    (same orientation as Docling TOPLEFT), y_bottom from PDF bottom-left.
    """
    try:
        import pypdf
    except Exception as exc:
        logger.debug("[docling_table_geometry] pypdf unavailable: %s", exc)
        return [], 0.0

    try:
        reader = pypdf.PdfReader(BytesIO(pdf_bytes))
    except Exception as exc:
        logger.debug("[docling_table_geometry] PdfReader failed: %s", exc)
        return [], 0.0

    if page_index < 0 or page_index >= len(reader.pages):
        return [], 0.0

    page = reader.pages[page_index]
    height = float(page.mediabox.height)
    collected: List[PdfWord] = []

    def _visitor(text: str, _cm, tm, _font_dict, _font_size) -> None:
        raw = (text or "").replace("\n", " ").strip()
        if not raw:
            return
        try:
            x = float(tm[4])
            y_bottom = float(tm[5])
        except Exception:
            return
        collected.append(
            PdfWord(
                x=x,
                y_bottom=y_bottom,
                y_top=height - y_bottom,
                text=raw,
            )
        )

    try:
        page.extract_text(visitor_text=_visitor)
    except Exception as exc:
        logger.debug("[docling_table_geometry] extract_text visitor failed: %s", exc)
        return [], height

    return collected, height


def _cell_text(cell: Any) -> str:
    return str(getattr(cell, "text", None) or "").strip()


def _bbox_dict(bbox: Any) -> Optional[Dict[str, float]]:
    if bbox is None:
        return None
    try:
        return {
            "l": float(bbox.l),
            "t": float(bbox.t),
            "r": float(bbox.r),
            "b": float(bbox.b),
        }
    except Exception:
        return None


def matrix_from_docling_table(table_item: Any) -> Optional[GeometryTable]:
    """Build header+rows matrix from Docling TableItem.data.grid."""
    data = getattr(table_item, "data", None)
    if data is None:
        return None
    grid = getattr(data, "grid", None)
    if not grid:
        return None

    matrix: List[List[str]] = []
    for row in grid:
        matrix.append([_cell_text(cell) for cell in row])
    if not matrix:
        return None

    # Prefer rows marked column_header; else first row.
    header_idx = 0
    for i, row in enumerate(grid):
        if any(bool(getattr(cell, "column_header", False)) for cell in row):
            header_idx = i
            break

    headers = matrix[header_idx]
    rows = [r for i, r in enumerate(matrix) if i != header_idx and any(c.strip() for c in r)]
    if not any(h.strip() for h in headers):
        return None
    return GeometryTable(headers=headers, rows=rows, source="docling_grid")


def _column_widths(col_boxes: Dict[int, Any]) -> Dict[int, float]:
    widths: Dict[int, float] = {}
    for idx, box in col_boxes.items():
        bd = _bbox_dict(box)
        if not bd:
            continue
        widths[int(idx)] = max(0.0, bd["r"] - bd["l"])
    return widths


def _words_in_bbox(
    words: Sequence[PdfWord],
    bbox: Dict[str, float],
    *,
    tol: float = 6.0,
) -> List[PdfWord]:
    return [
        w
        for w in words
        if bbox["l"] - tol <= w.x <= bbox["r"] + tol
        and bbox["t"] - tol <= w.y_top <= bbox["b"] + tol
    ]


def _largest_gap_split(xs: Sequence[float]) -> Optional[float]:
    uniq = sorted(set(float(x) for x in xs))
    if len(uniq) < 2:
        return None
    best_gap = 0.0
    best_mid: Optional[float] = None
    for a, b in zip(uniq, uniq[1:]):
        gap = b - a
        if gap > best_gap:
            best_gap = gap
            best_mid = (a + b) / 2.0
    if best_gap < _MIN_ROW_GAP_PT or best_mid is None:
        return None
    return best_mid


def _median_split_x_for_column(
    words: Sequence[PdfWord],
    col_bbox: Dict[str, float],
    row_boxes: Dict[int, Any],
    header_row_idx: int,
) -> Optional[float]:
    """Median X split from per-data-row largest gaps inside a wide column."""
    splits: List[float] = []
    for idx, box in row_boxes.items():
        if int(idx) == header_row_idx:
            continue
        rb = _bbox_dict(box)
        if not rb:
            continue
        # Intersect column with row band.
        band = {
            "l": col_bbox["l"],
            "r": col_bbox["r"],
            "t": rb["t"],
            "b": rb["b"],
        }
        row_words = _words_in_bbox(words, band, tol=4.0)
        if len(row_words) < 2:
            continue
        split = _largest_gap_split([w.x for w in row_words])
        if split is not None:
            splits.append(split)
    if len(splits) < _MIN_SPLIT_ROWS:
        return None
    return float(statistics.median(splits))


def _join_words(words: Sequence[PdfWord]) -> str:
    ordered = sorted(words, key=lambda w: (round(w.y_top, 1), w.x))
    parts: List[str] = []
    for w in ordered:
        if not parts or parts[-1] != w.text:
            parts.append(w.text)
    return " ".join(parts).strip()


def _split_cell_words(words: Sequence[PdfWord], split_x: float) -> Tuple[str, str]:
    left = [w for w in words if w.x < split_x]
    right = [w for w in words if w.x >= split_x]
    return _join_words(left), _join_words(right)


def refine_geometry_table(
    table_item: Any,
    *,
    pdf_words: Sequence[PdfWord],
) -> Optional[GeometryTable]:
    """
    Start from Docling grid; split anomalously wide columns via PDF word geometry.
    """
    base = matrix_from_docling_table(table_item)
    if base is None:
        return None
    if not pdf_words:
        return base

    data = getattr(table_item, "data", None)
    if data is None:
        return base

    try:
        col_boxes = data.get_column_bounding_boxes() or {}
        row_boxes = data.get_row_bounding_boxes() or {}
    except Exception:
        return base

    widths = _column_widths(col_boxes)
    if len(widths) < 2:
        return base

    sibling = [w for i, w in widths.items() if w > 0]
    if len(sibling) < 2:
        return base
    median_w = statistics.median(sibling)

    # Header row index in Docling grid.
    grid = data.grid
    header_row_idx = 0
    for i, row in enumerate(grid):
        if any(bool(getattr(cell, "column_header", False)) for cell in row):
            header_row_idx = i
            break

    headers = list(base.headers)
    rows = [list(r) for r in base.rows]
    changed = False

    # Split from right to left so indices stay stable while inserting.
    for col_idx in sorted(widths.keys(), reverse=True):
        width = widths[col_idx]
        if width < median_w * _WIDE_COLUMN_RATIO:
            continue
        box = _bbox_dict(col_boxes.get(col_idx))
        if not box:
            continue
        if col_idx >= len(headers):
            continue

        split_x = _median_split_x_for_column(
            pdf_words, box, row_boxes, header_row_idx=header_row_idx
        )
        if split_x is None:
            continue

        # Header split.
        header_box = _bbox_dict(row_boxes.get(header_row_idx))
        if header_box:
            header_band = {
                "l": box["l"],
                "r": box["r"],
                "t": header_box["t"],
                "b": header_box["b"],
            }
            h_left, h_right = _split_cell_words(
                _words_in_bbox(pdf_words, header_band, tol=5.0), split_x
            )
        else:
            h_left, h_right = headers[col_idx], ""

        if not h_left and not h_right:
            continue
        # Require both sides non-empty for a real visual split.
        if not h_left or not h_right:
            # Fall back: keep Docling header text on the wider/right side label
            # only if data rows still split cleanly — otherwise skip.
            continue

        new_headers = headers[:col_idx] + [h_left, h_right] + headers[col_idx + 1 :]
        new_rows: List[List[str]] = []
        # Map Docling data row i -> row_boxes key (skip header index in grid).
        data_row_keys = [k for k in sorted(row_boxes.keys()) if int(k) != header_row_idx]
        for r_i, row in enumerate(rows):
            if col_idx >= len(row):
                new_rows.append(row)
                continue
            rb_key = data_row_keys[r_i] if r_i < len(data_row_keys) else None
            rb = _bbox_dict(row_boxes.get(rb_key)) if rb_key is not None else None
            if rb:
                band = {"l": box["l"], "r": box["r"], "t": rb["t"], "b": rb["b"]}
                left, right = _split_cell_words(
                    _words_in_bbox(pdf_words, band, tol=4.0), split_x
                )
            else:
                left, right = row[col_idx], ""
            new_rows.append(row[:col_idx] + [left, right] + row[col_idx + 1 :])

        headers = new_headers
        rows = new_rows
        changed = True
        logger.info(
            "[docling_table_geometry] split wide column %s at x=%.1f -> %r | %r",
            col_idx,
            split_x,
            h_left,
            h_right,
        )

    if not changed:
        return base
    return GeometryTable(headers=headers, rows=rows, source="docling_grid+pdf_geometry")


def geometry_table_to_markdown(table: GeometryTable) -> str:
    """Serialize a geometry table to markdown pipes for downstream parsers."""
    cols = max(len(table.headers), max((len(r) for r in table.rows), default=0))
    if cols <= 0:
        return ""

    def _pad(cells: Sequence[str]) -> List[str]:
        out = [str(c or "").replace("|", "\\|").replace("\n", " ").strip() for c in cells]
        if len(out) < cols:
            out.extend([""] * (cols - len(out)))
        return out[:cols]

    header = _pad(table.headers)
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * cols) + "|",
    ]
    for row in table.rows:
        lines.append("| " + " | ".join(_pad(row)) + " |")
    return "\n".join(lines) + "\n"


def export_table_item_geometry(
    table_item: Any,
    *,
    doc: Any = None,
    pdf_bytes: Optional[bytes] = None,
    page_no: Optional[int] = None,
) -> Optional[GeometryTable]:
    """
    Structured table matrix from Docling TableItem (grid + optional PDF geometry).

    Prefer this over markdown for statement indexing — keeps native cells.
    """
    del doc  # reserved for exporters parity
    words: List[PdfWord] = []
    if pdf_bytes and page_no is not None and int(page_no) >= 1:
        words, _height = extract_pdf_page_words(pdf_bytes, int(page_no) - 1)

    refined = refine_geometry_table(table_item, pdf_words=words)
    if refined is not None and refined.headers:
        return refined

    base = matrix_from_docling_table(table_item)
    if base is not None and base.headers:
        return base
    return None


def export_table_item_markdown(
    table_item: Any,
    *,
    doc: Any = None,
    pdf_bytes: Optional[bytes] = None,
    page_no: Optional[int] = None,
) -> str:
    """
    Best-effort markdown for a Docling TableItem.

    PDF page_no is 1-based (Docling convention). Falls back to export_to_markdown.
    """
    refined = export_table_item_geometry(
        table_item, doc=doc, pdf_bytes=pdf_bytes, page_no=page_no
    )
    if refined is not None and refined.headers:
        return geometry_table_to_markdown(refined)

    # Fallback: Docling native exporters.
    try:
        md = table_item.export_to_markdown(doc=doc)
        if md and str(md).strip():
            return str(md).strip() + "\n"
    except Exception:
        pass
    try:
        df = table_item.export_to_dataframe(doc=doc)
        return df.to_markdown(index=False).strip() + "\n"
    except Exception:
        return ""


def shard_geometry_table(
    table: GeometryTable,
    *,
    rows_per_group: int,
) -> List[GeometryTable]:
    """Split a large table into header + row groups (mirrors markdown sharding)."""
    n = max(1, int(rows_per_group or 8))
    if len(table.rows) <= n:
        return [table]
    out: List[GeometryTable] = []
    for i in range(0, len(table.rows), n):
        chunk = table.rows[i : i + n]
        out.append(
            GeometryTable(
                headers=list(table.headers),
                rows=[list(r) for r in chunk],
                source=table.source,
            )
        )
    return out
