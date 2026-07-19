"""
Native digital-PDF statement table extraction.

World-class approach for bank statements with a text layer:

1. Prefer real table structure (PyMuPDF find_tables) when ruled grids exist.
2. Prefer Camelot network for borderless whitespace tables.
3. Map columns from **header labels**, never from X/Y guessing.
4. Score candidates; reject low-quality extractions.
5. Geometry-first guessing stays outside this module (optional last resort).

No invented amounts: cell text comes from the PDF text layer only.
"""
from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from app.services.table_schema_normalize import (
    ColumnRole,
    cell_looks_like_amount,
    normalize_amount_cell,
)

logger = logging.getLogger(__name__)

_DATE_RE = re.compile(r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b")
_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}$")
_CARD_LAST4_RE = re.compile(r"^\d{4}$")
# Statement amounts: allow 1–2 decimals (VTB "-139.9") and currency suffixes.
_MONEY_CELL_RE = re.compile(
    r"^[+\-−]?\s*\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{1,2})?"
    r"(?:\s*(?:₽|руб\.?|RUB|USD|EUR))?$"
    r"|^[+\-−]?\d+[.,]\d{1,2}$",
    re.IGNORECASE,
)


def _cell_is_money(value: str) -> bool:
    text = (value or "").strip().replace("\u2212", "-").replace("\u00a0", " ")
    if not text or _CARD_LAST4_RE.fullmatch(text):
        return False
    if cell_looks_like_amount(text):
        return True
    return bool(_MONEY_CELL_RE.match(text))

_HEADER_DATE_RE = re.compile(r"(?i)дата|date|время|time")
_HEADER_DESC_RE = re.compile(
    r"(?i)описан|назнач|detail|merchant|контрагент|получател|плательщик"
)
_HEADER_CATEGORY_RE = re.compile(r"(?i)категор|category")
_HEADER_BALANCE_RE = re.compile(r"(?i)остат|balance|сальдо")
_HEADER_AMOUNT_RE = re.compile(r"(?i)сумм|amount|debit|credit|дебет|кредит")
_HEADER_SKIP_AMOUNT_RE = re.compile(
    r"(?i)комисс|номер\s*карт|card\s*number|auth|авторизац"
)
_HEADER_OP_CURRENCY_RE = re.compile(
    r"(?i)валюте\s+операц|currency\s+of\s+operat|в\s+валюте\s+операц"
)
_HEADER_CARD_CURRENCY_RE = re.compile(
    r"(?i)валюте\s+карт|currency\s+of\s+card|в\s+валюте\s+карт|сумма\s+операции\s+в\s+валюте\s+карт"
)

_CANONICAL_HEADERS = {
    ColumnRole.DATE: "Дата операции",
    ColumnRole.DESCRIPTION: "Описание",
    ColumnRole.CATEGORY: "Категория",
    ColumnRole.AMOUNT: "Сумма",
    ColumnRole.BALANCE: "Остаток",
}


@dataclass(frozen=True)
class StatementNativeRow:
    date_text: str
    amount_raw: str
    description: str
    balance_raw: str = ""
    page: int = 1  # 1-based
    # Full row aligned to StatementNativeResult.headers (original PDF columns).
    cells: Tuple[str, ...] = ()


@dataclass
class StatementNativeResult:
    strategy: str
    rows: List[StatementNativeRow] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    column_roles: List[str] = field(default_factory=list)
    score: float = 0.0
    rejection: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.rows) and not self.rejection

    @property
    def primary_amount_header(self) -> str:
        for header, role in zip(self.headers, self.column_roles):
            if role == ColumnRole.AMOUNT.value:
                return header
        return ""


def _norm_cell(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


def _has_date(text: str) -> bool:
    return bool(_DATE_RE.search(text or ""))


def amount_header_preference(header: str) -> int:
    """
    Rank amount-like headers. Prefer card-currency / operation sum;
    demote commission, card number, and 'amount in operation currency'
    when a better sibling exists (VTB pattern).
    """
    h = (header or "").strip()
    if not h:
        return -1000
    if _HEADER_SKIP_AMOUNT_RE.search(h):
        return -1000
    if not _HEADER_AMOUNT_RE.search(h):
        return -100
    score = 20
    if _HEADER_CARD_CURRENCY_RE.search(h) or re.search(r"(?i)карт", h):
        score += 80
    if _HEADER_OP_CURRENCY_RE.search(h) and not re.search(r"(?i)карт", h):
        score -= 60
    if re.search(r"(?i)дебет|кредит|debit|credit", h):
        score += 30
    return score


def infer_role_for_header(header: str) -> ColumnRole:
    h = (header or "").strip()
    if not h:
        return ColumnRole.OTHER
    if _HEADER_SKIP_AMOUNT_RE.search(h) and not _HEADER_AMOUNT_RE.search(h):
        return ColumnRole.OTHER
    if _HEADER_DATE_RE.search(h):
        return ColumnRole.DATE
    if _HEADER_DESC_RE.search(h):
        return ColumnRole.DESCRIPTION
    if _HEADER_CATEGORY_RE.search(h):
        return ColumnRole.CATEGORY
    if _HEADER_BALANCE_RE.search(h):
        return ColumnRole.BALANCE
    if amount_header_preference(h) >= 0:
        return ColumnRole.AMOUNT
    return ColumnRole.OTHER


def map_headers_to_roles(headers: Sequence[str]) -> List[ColumnRole]:
    """
    Assign roles from header text. At most one AMOUNT column — the best
    amount-like header wins; others become OTHER.
    """
    raw = [infer_role_for_header(h) for h in headers]
    amount_idxs = [
        i
        for i, (h, role) in enumerate(zip(headers, raw))
        if role == ColumnRole.AMOUNT or amount_header_preference(h) >= 0
    ]
    if not amount_idxs:
        return raw

    best_i = max(amount_idxs, key=lambda i: amount_header_preference(headers[i]))
    out: List[ColumnRole] = []
    for i, role in enumerate(raw):
        if i == best_i:
            out.append(ColumnRole.AMOUNT)
        elif role == ColumnRole.AMOUNT or (
            amount_header_preference(headers[i]) >= 0 and i != best_i
        ):
            # Secondary money columns (commission, op-currency zeros) stay OTHER.
            if role in (ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.CATEGORY, ColumnRole.BALANCE):
                out.append(role)
            else:
                out.append(ColumnRole.OTHER)
        else:
            out.append(role)
    return out


def _find_header_row(matrix: Sequence[Sequence[str]], *, max_scan: int = 4) -> int:
    best_i = 0
    best_score = -1
    for i, row in enumerate(list(matrix)[:max_scan]):
        joined = " ".join(_norm_cell(c) for c in row).lower()
        score = 0
        if "дата" in joined or "date" in joined:
            score += 2
        if "сумм" in joined or "amount" in joined:
            score += 2
        if "описан" in joined or "назнач" in joined:
            score += 2
        if score > best_score:
            best_score = score
            best_i = i
    return best_i if best_score >= 2 else 0


def _is_header_continuation(row: Sequence[str]) -> bool:
    """Camelot often splits headers across two lines (Дата / операции)."""
    cells = [_norm_cell(c) for c in row]
    if not cells:
        return False
    if _has_date(cells[0]):
        return False
    joined = " ".join(cells).lower()
    return bool(
        re.search(r"операци|списан|валюте|карт|описан", joined)
        and not _cell_is_money(joined)
    )


def uniquify_headers(headers: Sequence[str]) -> List[str]:
    """Stable unique labels so row_columns dict never collapses siblings."""
    seen: dict[str, int] = {}
    out: List[str] = []
    for i, raw in enumerate(headers):
        base = (raw or "").strip() or f"Колонка {i + 1}"
        count = seen.get(base, 0)
        seen[base] = count + 1
        out.append(base if count == 0 else f"{base} ({count + 1})")
    return out


def project_row_by_roles(
    cells: Sequence[str],
    roles: Sequence[ColumnRole],
) -> Optional[StatementNativeRow]:
    date = ""
    amount = ""
    desc = ""
    balance = ""
    category = ""
    normalized_cells = [_norm_cell(c) for c in cells]
    while len(normalized_cells) < len(roles):
        normalized_cells.append("")
    normalized_cells = normalized_cells[: len(roles)]

    for cell, role in zip(normalized_cells, roles):
        text = cell
        if role == ColumnRole.DATE and text and not date:
            date = text
        elif role == ColumnRole.AMOUNT and text and not amount:
            amount = text
        elif role == ColumnRole.DESCRIPTION and text:
            desc = f"{desc} {text}".strip() if desc else text
        elif role == ColumnRole.CATEGORY and text and not category:
            category = text
        elif role == ColumnRole.BALANCE and text and not balance:
            balance = text

    narrative = desc or category
    if not _has_date(date) and not (amount and _cell_is_money(amount)):
        return None
    if amount and not _cell_is_money(amount):
        # Reject card last-4 mistaken as amount.
        if _CARD_LAST4_RE.fullmatch(amount.strip()):
            return None
    if not amount.strip():
        return None
    # Skip pure zero currency placeholders when nothing else useful
    normalized = normalize_amount_cell(amount) or amount
    if re.fullmatch(r"[+\-]?0+(?:[.,]0+)?(?:\s*(?:₽|руб\.?|RUB))?", normalized.replace(" ", ""), re.I):
        # Keep only if description exists? For VTB we must not keep 0.0 RUB op-currency.
        # Caller should have mapped the card-currency column; if we still have 0, drop.
        if not narrative:
            return None
        # If amount is literally 0.0 RUB and we have a narrative, still drop — wrong column.
        if "0.0" in amount.replace(",", ".") and "RUB" in amount.upper():
            return None

    return StatementNativeRow(
        date_text=date,
        amount_raw=amount,
        description=narrative,
        balance_raw=balance,
        cells=tuple(normalized_cells),
    )


def _merge_continuation_into_cells(
    *,
    cells: Tuple[str, ...],
    roles: Sequence[ColumnRole],
    new_date: str,
    new_desc: str,
    extras: Sequence[str],
) -> Tuple[str, ...]:
    """Keep full PDF row; fold wrap/time fragments into date/description cells."""
    out = list(cells)
    while len(out) < len(roles):
        out.append("")
    for i, role in enumerate(roles):
        if role == ColumnRole.DATE:
            out[i] = new_date
        elif role == ColumnRole.DESCRIPTION and new_desc:
            out[i] = new_desc
        elif role == ColumnRole.CATEGORY and new_desc and not out[i].strip():
            out[i] = new_desc
    # If description role missing, append leftover text into first non-money text cell.
    if new_desc and not any(r == ColumnRole.DESCRIPTION for r in roles):
        for i, role in enumerate(roles):
            if role in (ColumnRole.AMOUNT, ColumnRole.BALANCE, ColumnRole.DATE):
                continue
            if not _cell_is_money(out[i]):
                out[i] = f"{out[i]} {new_desc}".strip() if out[i] else new_desc
                break
    return tuple(out[: len(roles)])


def matrix_to_rows(
    matrix: Sequence[Sequence[str]],
    *,
    page: int = 1,
) -> Tuple[List[str], List[ColumnRole], List[StatementNativeRow]]:
    if not matrix:
        return [], [], []
    header_i = _find_header_row(matrix)
    headers = [_norm_cell(c) for c in matrix[header_i]]
    # Drop empty trailing headers
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        return [], [], []

    roles = map_headers_to_roles(headers)
    start = header_i + 1
    if start < len(matrix) and _is_header_continuation(matrix[start]):
        # Merge continuation header labels into headers for readability
        cont = [_norm_cell(c) for c in matrix[start]]
        merged_headers = []
        for a, b in zip(headers, cont + [""] * len(headers)):
            label = f"{a} {b}".strip() if b and b.lower() not in a.lower() else a
            merged_headers.append(label or a)
        headers = merged_headers[: len(roles)] or headers
        roles = map_headers_to_roles(headers)
        start += 1

    headers = uniquify_headers(headers)
    rows: List[StatementNativeRow] = []
    pending: Optional[StatementNativeRow] = None
    for raw in matrix[start:]:
        cells = [_norm_cell(c) for c in raw]
        while len(cells) < len(roles):
            cells.append("")
        cells = cells[: len(roles)]

        projected = project_row_by_roles(cells, roles)
        if projected is not None and _has_date(projected.date_text):
            if pending is not None:
                rows.append(pending)
            pending = StatementNativeRow(
                date_text=projected.date_text,
                amount_raw=projected.amount_raw,
                description=projected.description,
                balance_raw=projected.balance_raw,
                page=page,
                cells=projected.cells or tuple(cells),
            )
            continue

        # Continuation line (time / wrapped description) — append to open row.
        if pending is None:
            continue
        extras = [
            c
            for c in cells
            if c
            and not _CARD_LAST4_RE.fullmatch(c)
            and not _cell_is_money(c)
        ]
        if not extras:
            continue
        extra_text = " ".join(extras).strip()
        new_date = pending.date_text
        if _TIME_ONLY_RE.match(extras[0]) and ":" not in pending.date_text:
            new_date = f"{pending.date_text} {extras[0]}"
            extra_text = " ".join(extras[1:]).strip()
        new_desc = f"{pending.description} {extra_text}".strip() if extra_text else pending.description
        new_cells = _merge_continuation_into_cells(
            cells=pending.cells or tuple(cells),
            roles=roles,
            new_date=new_date,
            new_desc=new_desc,
            extras=extras,
        )
        pending = StatementNativeRow(
            date_text=new_date,
            amount_raw=pending.amount_raw,
            description=new_desc,
            balance_raw=pending.balance_raw,
            page=pending.page,
            cells=new_cells,
        )

    if pending is not None:
        rows.append(pending)
    return headers, roles, rows


def score_native_result(result: StatementNativeResult) -> float:
    """Higher is better. 0..100."""
    rows = result.rows
    if not rows:
        return 0.0
    n = len(rows)
    with_amount = 0
    with_date = 0
    with_desc = 0
    nonzero = 0
    for row in rows:
        if _has_date(row.date_text):
            with_date += 1
        if row.amount_raw.strip() and _cell_is_money(row.amount_raw):
            with_amount += 1
            normalized = normalize_amount_cell(row.amount_raw) or row.amount_raw
            if not re.fullmatch(
                r"[+\-]?0+(?:[.,]0+)?",
                re.sub(r"[^\d.,+\-]", "", normalized.replace(" ", "")) or "0",
            ):
                nonzero += 1
        if (row.description or "").strip():
            with_desc += 1

    amount_ratio = with_amount / n
    date_ratio = with_date / n
    desc_ratio = with_desc / n
    nonzero_ratio = nonzero / n
    if nonzero_ratio < 0.5:
        return max(0.0, 20.0 * nonzero_ratio)
    score = (
        40.0 * nonzero_ratio
        + 25.0 * date_ratio
        + 25.0 * desc_ratio
        + 10.0 * min(1.0, n / 20.0)
    )
    # Soft penalty if amounts present but almost no descriptions (geometry-like).
    if desc_ratio < 0.15 and n >= 10:
        score *= 0.55
    if amount_ratio < 0.8:
        score *= 0.7
    return round(min(100.0, score), 2)


def result_to_canonical_matrix(
    result: StatementNativeResult,
) -> Tuple[List[str], List[List[str]], List[str]]:
    """
    Emit the original PDF table shape for indexing.

    Prefer full ``row.cells`` aligned to ``result.headers``. Fall back to a
    compact date/description/amount[/balance] projection only when cells are
    missing (legacy / geometry-shaped rows).
    """
    headers = uniquify_headers(result.headers) if result.headers else []
    roles = list(result.column_roles)

    has_full = bool(headers) and any(row.cells for row in result.rows)
    if has_full:
        # Align roles length to headers.
        while len(roles) < len(headers):
            roles.append(ColumnRole.OTHER.value)
        roles = roles[: len(headers)]
        matrix: List[List[str]] = []
        for row in result.rows:
            cells = list(row.cells) if row.cells else []
            while len(cells) < len(headers):
                cells.append("")
            matrix.append(cells[: len(headers)])
        return headers, matrix, roles

    # Fallback compact projection (geometry-compatible).
    headers = [
        _CANONICAL_HEADERS[ColumnRole.DATE],
        _CANONICAL_HEADERS[ColumnRole.DESCRIPTION],
        _CANONICAL_HEADERS[ColumnRole.AMOUNT],
    ]
    roles = [
        ColumnRole.DATE.value,
        ColumnRole.DESCRIPTION.value,
        ColumnRole.AMOUNT.value,
    ]
    has_balance = any((r.balance_raw or "").strip() for r in result.rows)
    if has_balance:
        headers.append(_CANONICAL_HEADERS[ColumnRole.BALANCE])
        roles.append(ColumnRole.BALANCE.value)

    matrix = []
    for row in result.rows:
        values = [row.date_text, row.description, row.amount_raw]
        if has_balance:
            values.append(row.balance_raw)
        matrix.append(values)
    return headers, matrix, roles


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def extract_via_pymupdf_tables(pdf_bytes: bytes) -> StatementNativeResult:
    try:
        import fitz  # noqa: PLC0415 — soft dependency already in requirements-core
    except Exception as exc:
        return StatementNativeResult(strategy="pymupdf_tables", rejection=f"no_fitz:{exc}")

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        return StatementNativeResult(strategy="pymupdf_tables", rejection=f"open_failed:{exc}")

    all_rows: List[StatementNativeRow] = []
    last_headers: List[str] = []
    last_roles: List[ColumnRole] = []

    for page_index in range(doc.page_count):
        page = doc[page_index]
        try:
            finder = page.find_tables()
            tables = list(finder.tables) if finder else []
        except Exception as exc:
            logger.debug("[native_table] find_tables page %s: %s", page_index + 1, exc)
            continue
        for tab in tables:
            try:
                data = tab.extract() or []
            except Exception:
                continue
            matrix = [[_norm_cell(c) for c in row] for row in data]
            # Drop title-only first row ("Операции по карте")
            if matrix and len(matrix[0]) <= 2:
                joined = " ".join(matrix[0]).lower()
                if "операц" in joined and "дата" not in joined:
                    matrix = matrix[1:]
            headers, roles, rows = matrix_to_rows(matrix, page=page_index + 1)
            if not rows:
                continue
            if not last_headers:
                last_headers = headers
                last_roles = roles
            for row in rows:
                all_rows.append(row)

    if not all_rows:
        return StatementNativeResult(strategy="pymupdf_tables", rejection="no_tables")

    result = StatementNativeResult(
        strategy="pymupdf_tables",
        rows=all_rows,
        headers=last_headers,
        column_roles=[r.value for r in last_roles],
    )
    result.score = score_native_result(result)
    return result


def extract_via_camelot_network(pdf_bytes: bytes) -> StatementNativeResult:
    # Soft import: Camelot is optional at deploy time (ghostscript / opencv).
    try:
        import camelot  # noqa: PLC0415 — optional heavy dependency
    except Exception as exc:
        return StatementNativeResult(
            strategy="camelot_network", rejection=f"camelot_unavailable:{exc}"
        )

    path: Optional[str] = None
    strategy = "camelot_network"
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            path = tmp.name
        try:
            tables = camelot.read_pdf(path, pages="all", flavor="network")
        except Exception as exc:
            try:
                tables = camelot.read_pdf(path, pages="all", flavor="stream")
                strategy = "camelot_stream"
            except Exception as exc2:
                return StatementNativeResult(
                    strategy="camelot_network",
                    rejection=f"read_failed:{exc}|{exc2}",
                )
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    all_rows: List[StatementNativeRow] = []
    last_headers: List[str] = []
    last_roles: List[ColumnRole] = []

    for page_i, table in enumerate(tables):
        data = getattr(table, "data", None) or []
        matrix = [[_norm_cell(c) for c in row] for row in data]
        page_num = int(getattr(table, "page", None) or (page_i + 1))
        headers, roles, rows = matrix_to_rows(matrix, page=page_num)
        if not rows:
            continue
        if not last_headers:
            last_headers = headers
            last_roles = roles
        all_rows.extend(rows)

    if not all_rows:
        return StatementNativeResult(strategy=strategy, rejection="no_rows")

    result = StatementNativeResult(
        strategy=strategy,
        rows=all_rows,
        headers=last_headers,
        column_roles=[r.value for r in last_roles],
    )
    result.score = score_native_result(result)
    return result


def extract_best_native_statement_table(
    pdf_bytes: bytes,
    *,
    enable_camelot: bool = True,
    min_score: float = 55.0,
) -> Optional[StatementNativeResult]:
    """
    Run available native strategies and return the best scoring candidate.
    """
    if not pdf_bytes:
        return None

    candidates: List[StatementNativeResult] = []

    pymupdf_result = extract_via_pymupdf_tables(pdf_bytes)
    if pymupdf_result.rows:
        candidates.append(pymupdf_result)
        logger.info(
            "[native_table] pymupdf_tables rows=%s score=%.1f",
            len(pymupdf_result.rows),
            pymupdf_result.score,
        )
    else:
        logger.info(
            "[native_table] pymupdf_tables rejected: %s",
            pymupdf_result.rejection or "empty",
        )

    if enable_camelot:
        camelot_result = extract_via_camelot_network(pdf_bytes)
        if camelot_result.rows:
            candidates.append(camelot_result)
            logger.info(
                "[native_table] %s rows=%s score=%.1f",
                camelot_result.strategy,
                len(camelot_result.rows),
                camelot_result.score,
            )
        else:
            logger.info(
                "[native_table] camelot rejected: %s",
                camelot_result.rejection or "empty",
            )

    viable = [c for c in candidates if c.score >= min_score and c.rows]
    if not viable:
        return None
    winner = max(viable, key=lambda c: (c.score, len(c.rows)))
    logger.info(
        "[native_table] winner=%s score=%.1f rows=%s",
        winner.strategy,
        winner.score,
        len(winner.rows),
    )
    return winner
