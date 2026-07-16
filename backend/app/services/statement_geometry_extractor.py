"""
Geometry-first extraction of operation rows from digital PDF registers.

Used only after the document is classified as a statement/register.
Bank-agnostic: column roles come from date/amount token distributions and
X clustering — never merchant names or bank vocabularies.

Contract:
  - words with page coordinates → visual lines → column bands → operations
  - a new operation starts when the date band carries a date token
  - continuation lines (no date) append to the open description band
  - amount / balance come from money token clusters (left→amount, right→balance)
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.docling_table_geometry import PdfWord
from app.services.table_schema_normalize import (
    ColumnRole,
    cell_looks_like_amount,
    cell_looks_like_date,
    clean_cell_text,
    normalize_amount_cell,
)

logger = logging.getLogger(__name__)

_DATE_TOKEN_RE = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
)
_TIME_TOKEN_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_MONEY_TOKEN_RE = re.compile(
    r"^[+\-−]?\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})"
    r"(?:\s*(?:₽|руб\.?|RUB))?$"
    r"|^[+\-−]?\d+[.,]\d{2}$",
    re.IGNORECASE,
)
_PAGE_NOISE_RE = re.compile(
    r"(?i)^(стр\.?|page|лист)\s*\d+|\d+\s*/\s*\d+$|^[\d\s./-]{1,12}$"
)
# Statement page chrome that must never become part of an operation description.
# Bank-agnostic: continuation banners, authenticity seals, e-document / QR verify boilerplate.
_PAGE_CHROME_RE = re.compile(
    r"(?i)"
    r"(?:^|\b)(?:"
    r"продолжение\s+на\s+следующ\w*\s+страниц\w*"
    r"|для\s+проверки\s+подлинност\w*"
    r"|подлинност[ьи]\s+(?:электронн\w+\s+)?документ\w*"
    r"|формирован\w*\s+(?:электронн\w+\s+)?документ\w*"
    r"|электронн\w+\s+документ\w*\s+сформирован\w*"
    r"|документ\w*\s+сформирован\w*\s+(?:в|через|с\s+помощью)"
    # Verification instruction blocks printed in page margins/footers.
    r"|(?:^|\s)\d+\.\s+зайдите\s+в\s+приложение"
    r"|раздел\s+[«\"„]?выписки\s+и\s+справки"
    r"|отсканируйте\s+qr[-\s]?код"
    r"|получите\s+документ\s+в\s+электронн\w*\s+виде"
    r"|предоставляя\s+qr[-\s]?код\s+третьим"
    r"|действителен\b"
    r")"
)
# Structural auth / reference codes next to the date column (not merchant text).
_AUTH_CODE_RE = re.compile(r"^\d{4,8}$")
_CARD_MASK_RE = re.compile(r"^\*+\d{2,8}$")

_Y_LINE_TOL = 3.5
_COLUMN_GAP_PT = 28.0
_BAND_HALF_WIDTH = 36.0
_MIN_DATA_LINES_FOR_LAYOUT = 4
# Max gap between glyph pieces of a spaced amount ("5" + "741,92").
_MONEY_JOIN_GAP_PT = 14.0

HEADER_LABELS = {
    ColumnRole.DATE: "Дата операции",
    ColumnRole.CATEGORY: "Категория",
    ColumnRole.AMOUNT: "Сумма",
    ColumnRole.BALANCE: "Остаток",
}


@dataclass(frozen=True)
class GeometryLine:
    y: float
    words: Tuple[PdfWord, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()


@dataclass(frozen=True)
class ColumnLayout:
    date_x: float
    amount_x: Optional[float]
    balance_x: Optional[float]
    desc_x0: float
    desc_x1: float
    page_width: float


@dataclass(frozen=True)
class StatementOperation:
    page: int  # 1-based
    date_text: str
    category_text: str
    amount_raw: str
    balance_raw: str
    y_top: float


@dataclass
class StatementGeometryResult:
    operations: List[StatementOperation] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    column_roles: List[str] = field(default_factory=list)
    pages_scanned: int = 0
    layout: Optional[ColumnLayout] = None
    rejection: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.operations) and not self.rejection


def extract_page_words_pymupdf(pdf_bytes: bytes, page_index: int) -> Tuple[List[PdfWord], float, float]:
    """
    Prefer PyMuPDF words (stable tokens). Falls back to empty on failure.
    Returns (words, page_height, page_width).
    """
    try:
        import fitz
    except Exception as exc:
        logger.debug("[statement_geometry] pymupdf unavailable: %s", exc)
        return [], 0.0, 0.0

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        logger.debug("[statement_geometry] fitz.open failed: %s", exc)
        return [], 0.0, 0.0

    try:
        if page_index < 0 or page_index >= doc.page_count:
            return [], 0.0, 0.0
        page = doc.load_page(page_index)
        height = float(page.rect.height)
        width = float(page.rect.width)
        words: List[PdfWord] = []
        for item in page.get_text("words") or []:
            if len(item) < 5:
                continue
            x0, y0, x1, y1, text = item[0], item[1], item[2], item[3], item[4]
            raw = str(text or "").replace("\n", " ").strip()
            if not raw:
                continue
            words.append(
                PdfWord(
                    x=(float(x0) + float(x1)) / 2.0,
                    y_bottom=height - float(y1),
                    y_top=float(y0),
                    text=raw,
                )
            )
        return words, height, width
    finally:
        doc.close()


def cluster_lines(words: Sequence[PdfWord], *, y_tol: float = _Y_LINE_TOL) -> List[GeometryLine]:
    if not words:
        return []
    ordered = sorted(words, key=lambda w: (round(w.y_top, 1), w.x))
    lines: List[List[PdfWord]] = []
    for word in ordered:
        if not lines:
            lines.append([word])
            continue
        if abs(word.y_top - lines[-1][0].y_top) <= y_tol:
            lines[-1].append(word)
        else:
            lines.append([word])
    out: List[GeometryLine] = []
    for group in lines:
        group_sorted = tuple(sorted(group, key=lambda w: w.x))
        y = statistics.median(w.y_top for w in group_sorted)
        out.append(GeometryLine(y=float(y), words=group_sorted))
    return out


def _normalize_money_flat(text: str) -> str:
    return clean_cell_text(text).replace("\u2212", "-").replace("\u00a0", " ").strip()


def _is_money_token(text: str) -> bool:
    flat = _normalize_money_flat(text)
    if not flat:
        return False
    if _DATE_TOKEN_RE.fullmatch(flat):
        return False
    if _TIME_TOKEN_RE.fullmatch(flat):
        return False
    if cell_looks_like_amount(flat):
        return True
    compact = re.sub(r"\s+", "", flat)
    return bool(_MONEY_TOKEN_RE.match(flat) or _MONEY_TOKEN_RE.match(compact))


def _joined_money_candidates(line: GeometryLine) -> List[Tuple[str, float]]:
    """
    Rebuild spaced amounts ("5" "741,92" → "5 741,92") from adjacent glyphs.

    Returns list of (amount_text, x_center).
    """
    words = list(line.words)
    if not words:
        return []
    out: List[Tuple[str, float]] = []
    i = 0
    while i < len(words):
        parts = [words[i]]
        j = i + 1
        while j < len(words):
            prev = parts[-1]
            cur = words[j]
            gap = cur.x - prev.x
            if gap > _MONEY_JOIN_GAP_PT * 2.5:
                break
            trial = _normalize_money_flat(
                " ".join(p.text for p in parts + [cur])
            )
            # Keep joining while digits / separators stay amount-shaped.
            if not re.fullmatch(r"[+\-−]?\d[\d\s\u00a0]*([.,]\d{2})?", trial.replace(" ", " ")):
                if _is_money_token(trial):
                    parts.append(cur)
                    j += 1
                    continue
                break
            parts.append(cur)
            j += 1
        joined = _normalize_money_flat(" ".join(p.text for p in parts))
        if _is_money_token(joined):
            x_center = statistics.mean(p.x for p in parts)
            out.append((joined, float(x_center)))
            i = j
            continue
        if _is_money_token(words[i].text):
            out.append((_normalize_money_flat(words[i].text), float(words[i].x)))
        i += 1
    # Deduplicate overlapping joins (prefer longer text).
    out.sort(key=lambda t: (-len(t[0]), t[1]))
    unique: List[Tuple[str, float]] = []
    used_x: List[float] = []
    for text, x in out:
        if any(abs(x - ux) < 8.0 for ux in used_x):
            continue
        unique.append((text, x))
        used_x.append(x)
    unique.sort(key=lambda t: t[1])
    return unique


def _date_tokens_in_line(line: GeometryLine) -> List[PdfWord]:
    hits: List[PdfWord] = []
    for word in line.words:
        if cell_looks_like_date(word.text) or _DATE_TOKEN_RE.search(word.text or ""):
            hits.append(word)
    return hits


def _line_money_hits(line: GeometryLine) -> List[Tuple[str, float]]:
    return _joined_money_candidates(line)


def _cluster_x(values: Sequence[float], *, gap: float) -> List[float]:
    if not values:
        return []
    ordered = sorted(float(v) for v in values)
    clusters: List[List[float]] = [[ordered[0]]]
    for x in ordered[1:]:
        if abs(x - clusters[-1][-1]) <= gap:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [statistics.median(c) for c in clusters]


def _is_noise_line(line: GeometryLine) -> bool:
    text = line.text.strip()
    if not text:
        return True
    if _PAGE_NOISE_RE.match(text):
        return True
    # Pure repeating header fragments without money/date are skipped later by roles.
    return False


def _is_page_chrome_text(text: str) -> bool:
    """True for statement page banners/footers (not merchant narrative)."""
    raw = clean_cell_text(text or "")
    if not raw:
        return False
    return bool(_PAGE_CHROME_RE.search(raw))


def _is_page_chrome_line(line: GeometryLine) -> bool:
    """
    Drop page chrome lines so they never append to an open operation.

    Chrome lines almost never carry a money spine; if they somehow do, keep them
    as potential operations (fail open on money).
    """
    if not _is_page_chrome_text(line.text):
        return False
    if _line_money_hits(line):
        return False
    return True


def strip_statement_page_chrome(text: str) -> str:
    """
    Remove page-chrome clauses glued into a description cell.

    Applied on flush so spine lines that already mixed chrome tokens stay clean.
    """
    raw = clean_cell_text(text or "")
    if not raw or not _PAGE_CHROME_RE.search(raw):
        return raw
    # Cut from the first chrome match to end — chrome is always a trailing banner.
    match = _PAGE_CHROME_RE.search(raw)
    if not match:
        return raw
    cleaned = clean_cell_text(raw[: match.start()])
    return cleaned or raw


def learn_column_layout(
    lines: Sequence[GeometryLine],
    *,
    page_width: float,
) -> Optional[ColumnLayout]:
    """Infer date / description / amount / balance X bands from data-like lines."""
    date_xs: List[float] = []
    money_xs: List[float] = []
    data_lines = 0
    for line in lines:
        if _is_noise_line(line):
            continue
        dates = _date_tokens_in_line(line)
        monies = _line_money_hits(line)
        if dates and monies:
            data_lines += 1
            date_xs.extend(w.x for w in dates)
            money_xs.extend(x for _t, x in monies)
        elif monies and not dates:
            money_xs.extend(x for _t, x in monies)

    if data_lines < _MIN_DATA_LINES_FOR_LAYOUT or not date_xs or not money_xs:
        return None

    date_x = float(statistics.median(date_xs))
    money_centers = _cluster_x(money_xs, gap=_COLUMN_GAP_PT)
    amount_x: Optional[float] = None
    balance_x: Optional[float] = None
    if len(money_centers) >= 2:
        amount_x = float(money_centers[0])
        balance_x = float(money_centers[-1])
    elif len(money_centers) == 1:
        amount_x = float(money_centers[0])

    desc_x0 = date_x + _BAND_HALF_WIDTH * 0.6
    right_bound = amount_x if amount_x is not None else page_width * 0.72
    desc_x1 = max(desc_x0 + 40.0, float(right_bound) - _BAND_HALF_WIDTH)
    return ColumnLayout(
        date_x=date_x,
        amount_x=amount_x,
        balance_x=balance_x,
        desc_x0=desc_x0,
        desc_x1=desc_x1,
        page_width=float(page_width or 595.0),
    )


def _in_band(x: float, center: Optional[float], *, half: float = _BAND_HALF_WIDTH) -> bool:
    if center is None:
        return False
    return abs(x - center) <= half


def _pick_money_near(line: GeometryLine, center: Optional[float]) -> str:
    if center is None:
        return ""
    cands = [
        (text, x)
        for text, x in _line_money_hits(line)
        if _in_band(x, center, half=_BAND_HALF_WIDTH * 1.5)
    ]
    if not cands:
        return ""
    best = min(cands, key=lambda t: abs(t[1] - center))
    return normalize_amount_cell(best[0]) or clean_cell_text(best[0])


def _line_has_date_in_band(line: GeometryLine, layout: ColumnLayout) -> Optional[str]:
    dates = _date_tokens_in_line(line)
    if not dates:
        return None
    in_band = [w for w in dates if _in_band(w.x, layout.date_x, half=_BAND_HALF_WIDTH * 1.6)]
    pick = min(in_band or dates, key=lambda w: abs(w.x - layout.date_x))
    match = _DATE_TOKEN_RE.search(pick.text or "")
    if not match:
        return None
    time_bits = [
        w.text
        for w in line.words
        if _TIME_TOKEN_RE.fullmatch(clean_cell_text(w.text))
        and abs(w.x - pick.x) < 90
    ]
    date_txt = match.group(0)
    if time_bits:
        return f"{date_txt} {time_bits[0]}"
    return date_txt


def _is_money_spine(line: GeometryLine, layout: ColumnLayout) -> bool:
    """
    Head of an operation: date + at least one money token in amount/balance bands.

    Body continuation lines often also carry a date (posting date) but no money —
    those must NOT open a new operation.
    """
    if not _line_has_date_in_band(line, layout):
        return False
    amount = _pick_money_near(line, layout.amount_x)
    balance = _pick_money_near(line, layout.balance_x)
    if amount or balance:
        return True
    # Single money column layouts / untuned bands: any money on the line.
    return bool(_line_money_hits(line))


def _description_from_line(line: GeometryLine, layout: ColumnLayout) -> str:
    """Collect description tokens, dropping dates/times/auth/money/card masks."""
    parts: List[str] = []
    for word in line.words:
        tok = clean_cell_text(word.text)
        if not tok:
            continue
        if _DATE_TOKEN_RE.fullmatch(tok) or cell_looks_like_date(tok):
            continue
        if _TIME_TOKEN_RE.fullmatch(tok):
            continue
        if _AUTH_CODE_RE.fullmatch(tok):
            continue
        if _CARD_MASK_RE.fullmatch(tok):
            continue
        if _is_money_token(tok):
            continue
        # Skip amount/balance band leftovers even if not classified as money.
        if layout.amount_x is not None and _in_band(word.x, layout.amount_x):
            continue
        if layout.balance_x is not None and _in_band(word.x, layout.balance_x):
            continue
        # Prefer tokens in/near the description span; keep leftmost narrative too.
        if word.x < layout.desc_x0 - 20:
            continue
        if word.x > layout.desc_x1 + 25:
            continue
        parts.append(tok)
    return clean_cell_text(" ".join(parts))


def reconcile_page_layout(
    global_layout: ColumnLayout,
    local: Optional[ColumnLayout],
) -> ColumnLayout:
    """
    Keep money bands stable across pages.

    Local re-learning can latch onto description numerals or mid-row artifacts;
    only adopt local amount/balance centers when they stay near the file-level bands.
    """
    if local is None:
        return global_layout

    def _pick(
        global_x: Optional[float],
        local_x: Optional[float],
        *,
        max_drift: float = 55.0,
    ) -> Optional[float]:
        if global_x is None:
            return local_x
        if local_x is None:
            return global_x
        if abs(local_x - global_x) <= max_drift:
            return local_x
        return global_x

    amount_x = _pick(global_layout.amount_x, local.amount_x)
    balance_x = _pick(global_layout.balance_x, local.balance_x)
    date_x = local.date_x
    if abs(local.date_x - global_layout.date_x) > 40:
        date_x = global_layout.date_x
    desc_x0 = float(date_x) + _BAND_HALF_WIDTH * 0.6
    right = amount_x if amount_x is not None else global_layout.page_width * 0.72
    desc_x1 = max(desc_x0 + 40.0, float(right) - _BAND_HALF_WIDTH)
    return ColumnLayout(
        date_x=float(date_x),
        amount_x=amount_x,
        balance_x=balance_x,
        desc_x0=desc_x0,
        desc_x1=desc_x1,
        page_width=float(local.page_width or global_layout.page_width),
    )


def _assign_amount_balance(
    line: GeometryLine,
    layout: ColumnLayout,
) -> Tuple[str, str]:
    """Map money hits on a spine line to amount/balance cells."""
    amount = _pick_money_near(line, layout.amount_x)
    balance = _pick_money_near(line, layout.balance_x)
    hits = _line_money_hits(line)
    if amount and balance:
        return amount, balance
    if not hits:
        return amount, balance
    # Fall back: leftmost money → amount, rightmost → balance.
    if not amount and not balance:
        if len(hits) == 1:
            return normalize_amount_cell(hits[0][0]) or hits[0][0], ""
        return (
            normalize_amount_cell(hits[0][0]) or hits[0][0],
            normalize_amount_cell(hits[-1][0]) or hits[-1][0],
        )
    if not amount and hits:
        # Prefer the leftmost hit that is not the balance we already took.
        for text, x in hits:
            if balance and layout.balance_x is not None and _in_band(x, layout.balance_x):
                continue
            amount = normalize_amount_cell(text) or text
            break
        if not amount:
            amount = normalize_amount_cell(hits[0][0]) or hits[0][0]
    if not balance and len(hits) >= 2:
        balance = normalize_amount_cell(hits[-1][0]) or hits[-1][0]
    return amount, balance


_META_CATEGORY_RE = re.compile(
    r"(?i)расшифровка\s+операц|остаток\s+на\b.*\bсч[её]т|"
    r"номер\s+сч[её]та|карты,\s*привязанн|валюта\s+российск"
)


def _is_meta_operation(op: StatementOperation) -> bool:
    """Drop statement chrome (account header / table legend), not merchant rows."""
    cat = op.category_text or ""
    if _META_CATEGORY_RE.search(cat):
        return True
    # Legend lines are long and amount-less while carrying a stray balance.
    if not op.amount_raw and len(cat) > 120 and cat.casefold().count("операц") >= 2:
        return True
    return False


def extract_operations_from_page(
    lines: Sequence[GeometryLine],
    *,
    layout: ColumnLayout,
    page_no: int,
) -> List[StatementOperation]:
    """
    Build operations for one page using a locked column layout.

    Model: money-spine opens an operation; subsequent non-spine lines append
    description until the next money-spine. This matches multi-line register
    rows without bank-specific vocabulary.
    """
    ops: List[StatementOperation] = []
    open_op: Optional[Dict[str, object]] = None

    def flush() -> None:
        nonlocal open_op
        if not open_op:
            return
        category = strip_statement_page_chrome(
            clean_cell_text(str(open_op.get("category") or ""))
        )
        amount = str(open_op.get("amount") or "")
        balance = str(open_op.get("balance") or "")
        date_text = str(open_op.get("date") or "")
        if not date_text and not amount and not balance:
            open_op = None
            return
        ops.append(
            StatementOperation(
                page=int(page_no),
                date_text=date_text,
                category_text=category,
                amount_raw=amount,
                balance_raw=balance,
                y_top=float(open_op.get("y") or 0.0),
            )
        )
        open_op = None

    for line in lines:
        if _is_noise_line(line) or _is_page_chrome_line(line):
            continue

        if _is_money_spine(line, layout):
            flush()
            date_txt = _line_has_date_in_band(line, layout) or ""
            amount, balance = _assign_amount_balance(line, layout)
            open_op = {
                "date": date_txt,
                "category": strip_statement_page_chrome(
                    _description_from_line(line, layout)
                ),
                "amount": amount,
                "balance": balance,
                "y": line.y,
            }
            continue

        if open_op is None:
            continue

        desc = _description_from_line(line, layout)
        if desc and not _is_page_chrome_text(desc):
            prev = str(open_op.get("category") or "").strip()
            open_op["category"] = clean_cell_text(f"{prev} {desc}".strip())
        # Body lines almost never carry the primary amount; fill only if still empty.
        if not open_op.get("amount"):
            amount = _pick_money_near(line, layout.amount_x)
            if amount:
                open_op["amount"] = amount
        if not open_op.get("balance"):
            balance = _pick_money_near(line, layout.balance_x)
            if balance:
                open_op["balance"] = balance

    flush()
    return ops


def merge_layouts(layouts: Sequence[ColumnLayout]) -> Optional[ColumnLayout]:
    if not layouts:
        return None
    date_x = statistics.median(L.date_x for L in layouts)
    amounts = [L.amount_x for L in layouts if L.amount_x is not None]
    balances = [L.balance_x for L in layouts if L.balance_x is not None]
    width = statistics.median(L.page_width for L in layouts)
    amount_x = float(statistics.median(amounts)) if amounts else None
    balance_x = float(statistics.median(balances)) if balances else None
    desc_x0 = float(date_x) + _BAND_HALF_WIDTH * 0.6
    right = amount_x if amount_x is not None else float(width) * 0.72
    desc_x1 = max(desc_x0 + 40.0, right - _BAND_HALF_WIDTH)
    return ColumnLayout(
        date_x=float(date_x),
        amount_x=amount_x,
        balance_x=balance_x,
        desc_x0=desc_x0,
        desc_x1=desc_x1,
        page_width=float(width),
    )


def pdf_page_count(pdf_bytes: bytes) -> int:
    try:
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:
        try:
            from pypdf import PdfReader

            return len(PdfReader(BytesIO(pdf_bytes)).pages)
        except Exception:
            return 0


def probe_register_likelihood(
    pdf_bytes: bytes,
    *,
    sample_pages: int = 4,
) -> Tuple[bool, float, str]:
    """
    Cheap pre-Docling probe: does this digital PDF look like a columnar register?

    Returns (is_register, confidence 0..1, reason).
    """
    n_pages = pdf_page_count(pdf_bytes)
    if n_pages <= 0:
        return False, 0.0, "no_pages"

    indices = sorted(
        {
            0,
            min(1, n_pages - 1),
            min(max(n_pages // 2, 0), n_pages - 1),
            min(max(n_pages - 1, 0), n_pages - 1),
        }
    )[: max(1, sample_pages)]

    layouts: List[ColumnLayout] = []
    data_line_hits = 0
    pages_with_data = 0
    for idx in indices:
        words, _h, width = extract_page_words_pymupdf(pdf_bytes, idx)
        if len(words) < 20:
            continue
        lines = cluster_lines(words)
        layout = learn_column_layout(lines, page_width=width or 595.0)
        if layout is None:
            continue
        layouts.append(layout)
        page_data = 0
        for line in lines:
            if _date_tokens_in_line(line) and _line_money_hits(line):
                page_data += 1
        if page_data >= 3:
            pages_with_data += 1
            data_line_hits += page_data

    if pages_with_data == 0 or not layouts:
        return False, 0.0, "no_columnar_date_amount_lines"

    # Stable date X across sampled pages.
    date_spread = 0.0
    if len(layouts) >= 2:
        date_xs = [L.date_x for L in layouts]
        date_spread = max(date_xs) - min(date_xs)
    if date_spread > 55.0:
        return False, 0.2, "unstable_date_column"

    conf = min(
        1.0,
        0.35 * pages_with_data + 0.02 * min(data_line_hits, 40) + 0.25,
    )
    if conf < 0.55:
        return False, conf, "low_confidence"
    return True, conf, "columnar_register"


def extract_statement_operations(
    pdf_bytes: bytes,
    *,
    max_pages: Optional[int] = None,
) -> StatementGeometryResult:
    """
    Extract all operations from a digital PDF using geometry-first layout.
    """
    n_pages = pdf_page_count(pdf_bytes)
    if n_pages <= 0:
        return StatementGeometryResult(rejection="empty_pdf")

    limit = n_pages if max_pages is None else min(n_pages, max(1, int(max_pages)))
    sample_indices = list(range(min(limit, 5)))
    if limit > 5:
        sample_indices.append(limit // 2)

    layouts: List[ColumnLayout] = []
    for idx in sample_indices:
        words, _h, width = extract_page_words_pymupdf(pdf_bytes, idx)
        lines = cluster_lines(words)
        layout = learn_column_layout(lines, page_width=width or 595.0)
        if layout is not None:
            layouts.append(layout)

    layout = merge_layouts(layouts)
    if layout is None:
        return StatementGeometryResult(
            pages_scanned=limit,
            rejection="layout_not_learned",
        )

    operations: List[StatementOperation] = []
    for idx in range(limit):
        words, _h, width = extract_page_words_pymupdf(pdf_bytes, idx)
        if not words:
            continue
        lines = cluster_lines(words)
        local = learn_column_layout(lines, page_width=width or layout.page_width)
        use = reconcile_page_layout(layout, local)
        operations.extend(
            extract_operations_from_page(lines, layout=use, page_no=idx + 1)
        )

    operations = [op for op in operations if not _is_meta_operation(op)]

    columns = [
        HEADER_LABELS[ColumnRole.DATE],
        HEADER_LABELS[ColumnRole.CATEGORY],
        HEADER_LABELS[ColumnRole.AMOUNT],
    ]
    roles = [ColumnRole.DATE.value, ColumnRole.CATEGORY.value, ColumnRole.AMOUNT.value]
    if layout.balance_x is not None:
        columns.append(HEADER_LABELS[ColumnRole.BALANCE])
        roles.append(ColumnRole.BALANCE.value)

    return StatementGeometryResult(
        operations=operations,
        columns=columns,
        column_roles=roles,
        pages_scanned=limit,
        layout=layout,
    )


def operations_to_matrix(
    result: StatementGeometryResult,
) -> Tuple[List[str], List[List[str]], List[str]]:
    """Return (headers, data_rows, roles) for structured-table indexing."""
    headers = list(result.columns)
    roles = list(result.column_roles)
    rows: List[List[str]] = []
    has_balance = ColumnRole.BALANCE.value in roles
    for op in result.operations:
        row = [op.date_text, op.category_text, op.amount_raw]
        if has_balance:
            row.append(op.balance_raw)
        rows.append(row)
    return headers, rows, roles
