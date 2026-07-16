"""
Second-pass recovery of operation table cells via PDF word geometry.

When Docling TableFormer drops cells (or whole rows) on a text PDF, values are
usually still present in the page text layer at stable X bands.

This module (bank-agnostic — column roles + geometry only):

  1. learns amount / balance X bands from rows that already have money
  2. fills empty amount and balance cells near each incomplete row's Y
  3. prepends channel/category text from the amount line when only the
     merchant body survived in the grid
  4. inserts missing operation rows for amount+balance pairs on the page
     that are not claimed by the matrix — never invents values
"""
from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union

from app.services.docling_table_geometry import PdfWord
from app.services.table_schema_normalize import (
    ColumnRole,
    cell_looks_like_amount,
    clean_cell_text,
    normalize_amount_cell,
    normalize_text_cell,
    _is_thin_operation_head,
    _thin_head_text_is_prefix_of_body,
)

logger = logging.getLogger(__name__)

_Y_BUCKET = 1.0
# Multi-line bank rows put amount on the visual line *above* the merchant
# (~11–14 pt). Keep this wider than a single glyph line.
_Y_MATCH_TOL = 16.0
_Y_AMOUNT_ABOVE_BIAS = 14.0
_Y_LINE_TOL = 6.0
_Y_BODY_BELOW = 22.0
_X_BAND_PAD = 18.0
_DATE_TOKEN_RE = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
)
_TIME_TOKEN_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
_CARD_BODY_RE = re.compile(
    r"(?i)операци\w*\s+по\s+(?:карте|сч[её]ту|счету)\b"
)
_STOP_ANCHOR_RE = re.compile(
    r"(?i)^(операци\w*|карте|сч[её]ту|RUS|MOSKVA|MIRNYJ|MIRNYI|по|от|для|на|с)$"
)
_PURE_MONEY_WINDOW_RE = re.compile(
    r"^[+\-]?\s*\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?"
    r"(?:\s*(?:₽|руб\.?|RUB|USD|EUR))?$",
    re.IGNORECASE,
)
_AMBIGUOUS_SHORT_DEC_RE = re.compile(r"^\d{1,2}\.\d{2}$")


@dataclass(frozen=True)
class GeometryRecoverStats:
    amounts: int = 0
    balances: int = 0
    categories: int = 0
    rows_inserted: int = 0

    @property
    def total(self) -> int:
        return self.amounts + self.balances + self.categories + self.rows_inserted


def _role_list(roles: Sequence[Union[ColumnRole, str]]) -> List[ColumnRole]:
    out: List[ColumnRole] = []
    for r in roles:
        if isinstance(r, ColumnRole):
            out.append(r)
        else:
            try:
                out.append(ColumnRole(str(r)))
            except ValueError:
                out.append(ColumnRole.OTHER)
    return out


def _is_pure_money_window(raw: str) -> bool:
    flat = re.sub(r"\s+", " ", (raw or "").replace("\u2212", "-").strip())
    if not flat or not _PURE_MONEY_WINDOW_RE.match(flat):
        return False
    if _DATE_TOKEN_RE.fullmatch(flat) or _AMBIGUOUS_SHORT_DEC_RE.match(flat):
        return False
    return cell_looks_like_amount(flat)


def _money_candidates(words: Sequence[PdfWord]) -> List[Tuple[str, float, float]]:
    """
    Group glyphs by Y and emit normalized money tokens with (x_center, y_top).

    Prefers the shortest *pure* amount window (no merchant/date text pollution).
    """
    by_y: Dict[float, List[PdfWord]] = {}
    for w in words:
        key = round(float(w.y_top) / _Y_BUCKET) * _Y_BUCKET
        by_y.setdefault(key, []).append(w)

    found: List[Tuple[str, float, float]] = []
    seen: set[Tuple[str, int, int]] = set()
    for y, group in by_y.items():
        ordered = sorted(group, key=lambda w: w.x)
        i = 0
        while i < len(ordered):
            best: Optional[Tuple[str, float, float]] = None
            best_len = 0
            for j in range(i + 1, min(i + 6, len(ordered) + 1)):
                chunk = ordered[i:j]
                raw = " ".join(c.text for c in chunk)
                if not _is_pure_money_window(raw):
                    continue
                norm = normalize_amount_cell(raw)
                if not norm or not cell_looks_like_amount(norm):
                    continue
                xc = (chunk[0].x + chunk[-1].x) / 2.0
                best = (norm, xc, float(y))
                best_len = j - i
                break
            if best is not None:
                key = (best[0], int(best[1]), int(best[2]))
                if key not in seen:
                    seen.add(key)
                    found.append(best)
                i += max(1, best_len)
            else:
                i += 1
    return found


def _amount_norm_set(matrix: Sequence[Sequence[str]], idxs: Sequence[int]) -> set[str]:
    vals: set[str] = set()
    for row in matrix:
        for i in idxs:
            if i >= len(row):
                continue
            cell = clean_cell_text(row[i])
            if cell_looks_like_amount(cell):
                vals.add(normalize_amount_cell(cell))
    return vals


def _learn_money_x_band(
    money: Sequence[Tuple[str, float, float]],
    known: set[str],
) -> Optional[Tuple[float, float]]:
    """
    Learn an X band from known money tokens.

    With a single known value, keep a tight band around it (do not fall back to
    all page money — that merges amount and balance columns).
    """
    xs = [x for text, x, _y in money if text in known]
    if not xs:
        return None
    if len(xs) == 1:
        x0 = float(xs[0])
        return (x0 - 28.0, x0 + 28.0)
    xs_sorted = sorted(xs)
    if len(xs_sorted) >= 6:
        lo_i = max(0, len(xs_sorted) // 10)
        hi_i = min(len(xs_sorted) - 1, len(xs_sorted) - 1 - len(xs_sorted) // 10)
        xs_sorted = xs_sorted[lo_i : hi_i + 1]
    med = statistics.median(xs_sorted)
    core = [x for x in xs_sorted if abs(x - med) <= 40.0]
    if len(core) < 2:
        core = xs_sorted
    return (min(core) - _X_BAND_PAD, max(core) + _X_BAND_PAD)


def _learn_amount_x_band(
    money: Sequence[Tuple[str, float, float]],
    known_amounts: set[str],
) -> Optional[Tuple[float, float]]:
    return _learn_money_x_band(money, known_amounts)


def _anchor_tokens(text: str) -> List[str]:
    flat = normalize_text_cell(text)
    out: List[str] = []
    for tok in flat.replace(".", " ").replace(",", " ").split():
        if len(tok) < 4:
            continue
        if _STOP_ANCHOR_RE.match(tok):
            continue
        if _DATE_TOKEN_RE.fullmatch(tok):
            continue
        out.append(tok)
    return out[:6]


def _word_y_for_token(words: Sequence[PdfWord], token: str) -> List[float]:
    needle = token.lower()
    ys: List[float] = []
    for w in words:
        if needle in (w.text or "").lower():
            ys.append(float(w.y_top))
    return ys


def _estimate_row_y(
    words: Sequence[PdfWord],
    *,
    date_token: str,
    description: str,
) -> Optional[float]:
    """Prefer Y where date co-occurs with a distinctive description token."""
    date_ys = _word_y_for_token(words, date_token) if date_token else []
    anchors = _anchor_tokens(description)
    if date_ys and anchors:
        scored: List[Tuple[int, float]] = []
        for dy in date_ys:
            hits = 0
            for tok in anchors:
                for ay in _word_y_for_token(words, tok):
                    if abs(ay - dy) <= _Y_MATCH_TOL:
                        hits += 1
                        break
            scored.append((hits, dy))
        scored.sort(key=lambda t: (-t[0], t[1]))
        if scored and scored[0][0] > 0:
            return scored[0][1]
    if len(date_ys) == 1:
        return float(date_ys[0])
    for tok in anchors:
        ys = _word_y_for_token(words, tok)
        if ys:
            return float(statistics.median(ys))
    return None


def _search_ys_for_row(
    words: Sequence[PdfWord],
    *,
    date_token: str,
    description: str,
    row_y: Optional[float],
) -> List[float]:
    """Y anchors for money lookup (merchant line + amount line above + dates)."""
    ys: List[float] = []
    if row_y is not None:
        ys.append(float(row_y))
        ys.append(float(row_y) - _Y_AMOUNT_ABOVE_BIAS)

    def _near_row(candidates: Sequence[float], *, limit: int) -> List[float]:
        vals = [float(y) for y in candidates]
        if row_y is None:
            return vals[:limit]
        # Prefer page occurrences close to this row — shared channel/merchant
        # tokens must not pull money toward another op with the same wording.
        return sorted(vals, key=lambda y: abs(y - float(row_y)))[:limit]

    if date_token:
        ys.extend(_near_row(_word_y_for_token(words, date_token), limit=2))
    for tok in _anchor_tokens(description)[:3]:
        ys.extend(_near_row(_word_y_for_token(words, tok), limit=2))
    out: List[float] = []
    seen: set[int] = set()
    for y in ys:
        key = int(round(y * 10))
        if key in seen:
            continue
        seen.add(key)
        out.append(float(y))
    return out


def _in_band(x: float, band: Tuple[float, float]) -> bool:
    return band[0] <= x <= band[1]


def _pick_money_near(
    money: Sequence[Tuple[str, float, float]],
    *,
    band: Tuple[float, float],
    search_ys: Sequence[float],
    claimed: set[str],
    prefer_y: Optional[float] = None,
) -> Optional[Tuple[str, float, float]]:
    band_mid = (band[0] + band[1]) / 2.0
    cands = [
        (text, x, y)
        for text, x, y in money
        if (
            text not in claimed
            and _in_band(x, band)
            and any(abs(y - sy) <= _Y_MATCH_TOL for sy in search_ys)
        )
    ]
    if not cands:
        return None
    anchor = float(prefer_y) if prefer_y is not None else float(search_ys[0])

    def _key(t: Tuple[str, float, float]) -> Tuple[float, float, float]:
        _text, x, y = t
        return (
            min(abs(y - sy) for sy in search_ys),
            abs(y - (anchor - _Y_AMOUNT_ABOVE_BIAS * 0.5)),
            abs(x - band_mid),
        )

    cands.sort(key=_key)
    return cands[0]


def _words_on_line(
    words: Sequence[PdfWord],
    *,
    y: float,
    x_lo: float,
    x_hi: float,
    y_tol: float = _Y_LINE_TOL,
) -> List[PdfWord]:
    return sorted(
        [
            w
            for w in words
            if abs(float(w.y_top) - y) <= y_tol and x_lo <= float(w.x) <= x_hi
        ],
        key=lambda w: w.x,
    )


def _join_words(ws: Sequence[PdfWord]) -> str:
    return normalize_text_cell(" ".join((w.text or "").strip() for w in ws if (w.text or "").strip()))


def _date_x_cutoff(words: Sequence[PdfWord], money: Sequence[Tuple[str, float, float]]) -> float:
    """Right edge of typical date column: median X of date tokens on amount lines."""
    date_xs: List[float] = []
    for w in words:
        if _DATE_TOKEN_RE.fullmatch((w.text or "").strip()):
            date_xs.append(float(w.x))
    if date_xs:
        return float(statistics.median(date_xs)) + 55.0
    if money:
        return min(x for _t, x, _y in money) - 40.0
    return 120.0


def _text_band(date_cut: float, amount_band: Tuple[float, float]) -> Tuple[float, float]:
    return (date_cut, max(date_cut + 10.0, amount_band[0] - 4.0))


def _channel_text_on_amount_line(
    words: Sequence[PdfWord],
    *,
    amount_y: float,
    text_band: Tuple[float, float],
) -> str:
    """Non-date/time text between date and amount columns on the amount spine line."""
    parts: List[str] = []
    for w in _words_on_line(
        words, y=amount_y, x_lo=text_band[0], x_hi=text_band[1]
    ):
        tok = (w.text or "").strip()
        if not tok:
            continue
        if _DATE_TOKEN_RE.fullmatch(tok) or _TIME_TOKEN_RE.fullmatch(tok):
            continue
        if _is_pure_money_window(tok):
            continue
        parts.append(tok)
    return normalize_text_cell(" ".join(parts))


def _body_text_below(
    words: Sequence[PdfWord],
    *,
    head_y: float,
    text_band: Tuple[float, float],
) -> str:
    """Merchant / body line just below the amount spine (multi-line operation)."""
    body_ys = sorted(
        {
            round(float(w.y_top) / _Y_BUCKET) * _Y_BUCKET
            for w in words
            if head_y < float(w.y_top) <= head_y + _Y_BODY_BELOW
            and text_band[0] <= float(w.x) <= text_band[1]
        }
    )
    for by in body_ys:
        text = _join_words(
            _words_on_line(words, y=by, x_lo=text_band[0], x_hi=text_band[1])
        )
        if not text:
            continue
        if _DATE_TOKEN_RE.fullmatch(text.split()[0] if text.split() else ""):
            # Drop leading date/auth tokens — keep the rest as description body.
            toks = text.split()
            while toks and (
                _DATE_TOKEN_RE.fullmatch(toks[0])
                or _TIME_TOKEN_RE.fullmatch(toks[0])
                or re.fullmatch(r"\d{4,8}", toks[0] or "")
            ):
                toks.pop(0)
            text = normalize_text_cell(" ".join(toks))
        if text and (_CARD_BODY_RE.search(text) or len(text) >= 8):
            return text
    return ""


def _date_on_line(words: Sequence[PdfWord], *, y: float, x_hi: float) -> str:
    parts: List[str] = []
    for w in _words_on_line(words, y=y, x_lo=0.0, x_hi=x_hi, y_tol=_Y_LINE_TOL):
        tok = (w.text or "").strip()
        if _DATE_TOKEN_RE.fullmatch(tok) or _TIME_TOKEN_RE.fullmatch(tok):
            parts.append(tok)
        elif re.fullmatch(r"\d{4,8}", tok) and parts:
            # Auth code after date/time.
            parts.append(tok)
            break
    if not parts:
        return ""
    # Prefer "date time" or "date".
    date = next((p for p in parts if _DATE_TOKEN_RE.fullmatch(p)), parts[0])
    time = next((p for p in parts if _TIME_TOKEN_RE.fullmatch(p)), "")
    return normalize_text_cell(f"{date} {time}".strip())


def _merge_category(existing: str, channel: str, body: str) -> str:
    """Merge channel head + merchant body without duplicating substrings."""
    cur = normalize_text_cell(existing)
    ch = normalize_text_cell(channel)
    bd = normalize_text_cell(body)
    pieces: List[str] = []
    for part in (ch, cur, bd):
        if not part:
            continue
        if any(part.lower() in p.lower() or p.lower() in part.lower() for p in pieces):
            # Prefer the longer variant when one contains the other.
            for i, p in enumerate(pieces):
                if part.lower() in p.lower():
                    break
                if p.lower() in part.lower():
                    pieces[i] = part
                    break
            continue
        pieces.append(part)
    return normalize_text_cell(" ".join(pieces))


def _looks_like_body_only(text: str) -> bool:
    """
    Merchant/body fragment of a multi-line op (has card/account marker) that is
    missing its channel/category head on the amount spine line.
    """
    flat = normalize_text_cell(text)
    if not flat or not _CARD_BODY_RE.search(flat):
        return False
    if re.match(
        r"(?i)^(оплата|перевод|покупка|снятие|выдача|прочие\s+операц|супермаркет|"
        r"ресторан|транспорт|наличн)",
        flat,
    ):
        return False
    return True


def _spine_ops(
    money: Sequence[Tuple[str, float, float]],
    amount_band: Tuple[float, float],
    balance_band: Optional[Tuple[float, float]],
) -> List[Tuple[str, Optional[str], float]]:
    """
    Operation spines on the page: (amount, balance|None, y) from paired money tokens.

    Amount is the leftmost money in the amount band; balance is money in the
    balance band on the same Y (when present).
    """
    by_y: Dict[float, List[Tuple[str, float]]] = {}
    for text, x, y in money:
        key = round(float(y) / _Y_BUCKET) * _Y_BUCKET
        by_y.setdefault(key, []).append((text, x))

    ops: List[Tuple[str, Optional[str], float]] = []
    for y, group in sorted(by_y.items(), key=lambda t: t[0]):
        amts = sorted(
            [(t, x) for t, x in group if _in_band(x, amount_band)],
            key=lambda t: t[1],
        )
        if not amts:
            continue
        amount = amts[0][0]
        balance: Optional[str] = None
        if balance_band is not None:
            bals = sorted(
                [(t, x) for t, x in group if _in_band(x, balance_band)],
                key=lambda t: t[1],
            )
            if bals:
                balance = bals[0][0]
        ops.append((amount, balance, float(y)))
    return ops


def _empty_row(ncols: int) -> List[str]:
    return [""] * ncols


def recover_operation_table_from_page_geometry(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[Union[ColumnRole, str]],
    words: Sequence[PdfWord],
) -> Tuple[List[List[str]], GeometryRecoverStats]:
    """
    Recover amounts, balances, category heads, and missing rows from page words.

    Returns (updated_matrix, stats).
    """
    ncols = len(columns) if columns else (len(matrix[0]) if matrix else 0)
    if not words or ncols <= 0:
        return [list(r) for r in matrix], GeometryRecoverStats()

    role_list = _role_list(roles)
    while len(role_list) < ncols:
        role_list.append(ColumnRole.OTHER)

    amount_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.AMOUNT]
    balance_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.BALANCE]
    date_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.DATE]
    text_idxs = [
        i
        for i, r in enumerate(role_list)
        if r in (ColumnRole.CATEGORY, ColumnRole.DESCRIPTION)
    ]
    if not amount_idxs:
        return [list(r) for r in matrix], GeometryRecoverStats()

    money = _money_candidates(words)
    if not money:
        return [list(r) for r in matrix], GeometryRecoverStats()

    known_amounts = _amount_norm_set(matrix, amount_idxs)
    known_balances = _amount_norm_set(matrix, balance_idxs)
    amount_band = _learn_money_x_band(money, known_amounts)
    if amount_band is None:
        return [list(r) for r in matrix], GeometryRecoverStats()

    balance_band: Optional[Tuple[float, float]] = None
    if balance_idxs and known_balances:
        balance_band = _learn_money_x_band(money, known_balances)
    if balance_band is None and balance_idxs:
        # Infer balance band as money strictly to the right of the amount band.
        right = [x for _t, x, _y in money if x > amount_band[1]]
        if len(right) >= 1:
            balance_band = (min(right) - _X_BAND_PAD, max(right) + _X_BAND_PAD)
    if balance_band is not None and balance_band[0] < amount_band[1]:
        balance_band = (
            amount_band[1] + 4.0,
            max(balance_band[1], amount_band[1] + 40.0),
        )
    date_cut = _date_x_cutoff(words, money)
    text_band = _text_band(date_cut, amount_band)

    # Claim by geometry id so repeated money values (+2 000) stay distinct.
    claimed_money: set[Tuple[str, int, int]] = set()
    claimed_pairs: set[Tuple[str, str]] = set()

    def _money_id(text: str, x: float, y: float) -> Tuple[str, int, int]:
        return (text, int(round(x)), int(round(y)))

    def _claim_picked(picked: Tuple[str, float, float]) -> None:
        claimed_money.add(_money_id(picked[0], picked[1], picked[2]))

    def _balance_on_amount_line(amount_y: float, bal: str) -> bool:
        if not bal or balance_band is None:
            return False
        return any(
            bt == bal
            and abs(by - amount_y) <= _Y_LINE_TOL
            and _in_band(bx, balance_band)
            for bt, bx, by in money
        )

    working: List[List[str]] = [list(r) for r in matrix]

    def _row_desc(row: Sequence[str]) -> str:
        parts = [
            row[ti] for ti in text_idxs if ti < len(row) and clean_cell_text(row[ti])
        ]
        return " ".join(parts)

    # Pass 0: Docling sometimes puts money on a thin duplicated category head
    # while the merchant/body row (same spine Y) stays empty. Move money onto
    # the body when the thin head text is a prefix of that body.
    amounts_reassigned = 0
    donors_to_drop: set[int] = set()
    ai0 = amount_idxs[0]
    bi0 = balance_idxs[0] if balance_idxs else None
    for ri, row in enumerate(working):
        while len(row) <= ai0:
            row.append("")
        if cell_looks_like_amount(row[ai0]):
            continue
        body = _row_desc(row)
        if not body or len(body) < 8:
            continue
        if not (_CARD_BODY_RE.search(body) or len(body) >= 24):
            continue
        date_token = ""
        for di in date_idxs:
            if di < len(row):
                m = _DATE_TOKEN_RE.search(row[di] or "")
                if m:
                    date_token = m.group(0)
                    break
        row_y = _estimate_row_y(words, date_token=date_token, description=body)
        search_ys = _search_ys_for_row(
            words, date_token=date_token, description=body, row_y=row_y
        )
        if not search_ys:
            continue
        near = [
            (t, x, y)
            for t, x, y in money
            if _in_band(x, amount_band)
            and any(abs(y - sy) <= _Y_MATCH_TOL for sy in search_ys)
        ]
        near.sort(
            key=lambda t: min(abs(t[2] - sy) for sy in search_ys),
        )
        moved = False
        for amt_text, _ax, ay in near:
            for dj, donor in enumerate(working):
                if dj == ri or dj in donors_to_drop:
                    continue
                while len(donor) <= ai0:
                    donor.append("")
                if not cell_looks_like_amount(donor[ai0]):
                    continue
                if normalize_amount_cell(donor[ai0]) != amt_text:
                    continue
                donor_desc = _row_desc(donor)
                if not _is_thin_operation_head(donor_desc):
                    continue
                if not _thin_head_text_is_prefix_of_body(donor_desc, body):
                    continue
                donor_bal = ""
                if bi0 is not None and bi0 < len(donor) and cell_looks_like_amount(
                    donor[bi0]
                ):
                    donor_bal = normalize_amount_cell(donor[bi0])
                if donor_bal and not _balance_on_amount_line(ay, donor_bal):
                    # Donor amount text matches but its balance is not on this spine.
                    continue
                row[ai0] = donor[ai0]
                donor[ai0] = ""
                if bi0 is not None:
                    while len(row) <= bi0:
                        row.append("")
                    while len(donor) <= bi0:
                        donor.append("")
                    if donor_bal and not cell_looks_like_amount(row[bi0]):
                        row[bi0] = donor[bi0]
                        donor[bi0] = ""
                donors_to_drop.add(dj)
                amounts_reassigned += 1
                moved = True
                break
            if moved:
                break

    if donors_to_drop:
        working = [r for i, r in enumerate(working) if i not in donors_to_drop]

    def _bind_known_amount(
        amt: str,
        *,
        bal: str,
        search_ys: Sequence[float],
        prefer_y: Optional[float],
        allow_claimed: bool = False,
    ) -> Optional[Tuple[str, float, float]]:
        """
        Map a matrix amount cell to one page glyph.

        Prefer: (1) amount+balance co-located on the same spine,
        (2) closest to the row Y / date anchors — never the first glyph
        that merely shares description tokens elsewhere on the page.
        """
        cands = [
            (text, x, y)
            for text, x, y in money
            if text == amt
            and _in_band(x, amount_band)
            and (allow_claimed or _money_id(text, x, y) not in claimed_money)
        ]
        if not cands:
            return None
        if bal:
            paired = [c for c in cands if _balance_on_amount_line(c[2], bal)]
            # With a known balance, never fall back to an unpaired amount —
            # duplicate +2 000 spines would silently claim the wrong glyph.
            if not paired:
                return None
            pool = paired
        else:
            pool = cands
        anchor = float(prefer_y) if prefer_y is not None else (
            float(search_ys[0]) if search_ys else float(pool[0][2])
        )

        def _key(t: Tuple[str, float, float]) -> Tuple[int, float, float]:
            _text, _x, y = t
            near = (
                0
                if search_ys and any(abs(y - sy) <= _Y_MATCH_TOL for sy in search_ys)
                else 1
            )
            return (near, abs(y - anchor), abs(y - (anchor - _Y_AMOUNT_ABOVE_BIAS * 0.5)))

        pool.sort(key=_key)
        return pool[0]

    # Pre-claim glyphs for rows that already have amounts (ambiguous repeats).
    for row in working:
        amt = ""
        bal = ""
        for ai in amount_idxs:
            if ai < len(row) and cell_looks_like_amount(row[ai]):
                amt = normalize_amount_cell(row[ai])
        for bi in balance_idxs:
            if bi < len(row) and cell_looks_like_amount(row[bi]):
                bal = normalize_amount_cell(row[bi])
        if not amt:
            continue
        claimed_pairs.add((amt, bal))
        date_token = ""
        for di in date_idxs:
            if di < len(row):
                m = _DATE_TOKEN_RE.search(row[di] or "")
                if m:
                    date_token = m.group(0)
                    break
        description = _row_desc(row)
        pre_y = _estimate_row_y(words, date_token=date_token, description=description)
        pre_ys = _search_ys_for_row(
            words, date_token=date_token, description=description, row_y=pre_y
        )
        bound = None
        if bal:
            bound = _bind_known_amount(
                amt, bal=bal, search_ys=(), prefer_y=None, allow_claimed=False
            )
        if bound is None:
            bound = _bind_known_amount(
                amt,
                bal="",
                search_ys=pre_ys,
                prefer_y=pre_y,
                allow_claimed=False,
            )
        if bound is None:
            continue
        _claim_picked(bound)
        if bal:
            for bt, bx, by in money:
                if (
                    bt == bal
                    and abs(by - bound[2]) <= _Y_LINE_TOL
                    and (balance_band is None or _in_band(bx, balance_band))
                ):
                    _claim_picked((bt, bx, by))
                    break

    amounts_n = amounts_reassigned
    balances_n = 0
    categories_n = 0
    row_ys: List[Optional[float]] = []

    def _pick_unclaimed(
        *,
        band: Tuple[float, float],
        search_ys: Sequence[float],
        prefer_y: Optional[float],
    ) -> Optional[Tuple[str, float, float]]:
        # Allow duplicate text values; filter only exact geometry ids.
        band_mid = (band[0] + band[1]) / 2.0
        cands = [
            (text, x, y)
            for text, x, y in money
            if (
                _money_id(text, x, y) not in claimed_money
                and _in_band(x, band)
                and any(abs(y - sy) <= _Y_MATCH_TOL for sy in search_ys)
            )
        ]
        if not cands:
            return None
        anchor = float(prefer_y) if prefer_y is not None else float(search_ys[0])

        def _key(t: Tuple[str, float, float]) -> Tuple[float, float, float]:
            _text, x, y = t
            return (
                min(abs(y - sy) for sy in search_ys),
                abs(y - (anchor - _Y_AMOUNT_ABOVE_BIAS * 0.5)),
                abs(x - band_mid),
            )

        cands.sort(key=_key)
        return cands[0]

    # --- Pass 1: fill / enrich existing rows ---
    for row in working:
        date_token = ""
        for di in date_idxs:
            if di < len(row):
                m = _DATE_TOKEN_RE.search(row[di] or "")
                if m:
                    date_token = m.group(0)
                    break
        desc_parts = [
            row[ti] for ti in text_idxs if ti < len(row) and clean_cell_text(row[ti])
        ]
        description = " ".join(desc_parts)
        row_y = _estimate_row_y(words, date_token=date_token, description=description)
        search_ys = _search_ys_for_row(
            words, date_token=date_token, description=description, row_y=row_y
        )
        row_ys.append(row_y)

        if not search_ys:
            continue

        amount_y: Optional[float] = None

        # Amount
        ai = amount_idxs[0]
        while len(row) <= ai:
            row.append("")
        row_bal = ""
        if balance_idxs and balance_idxs[0] < len(row) and cell_looks_like_amount(
            row[balance_idxs[0]]
        ):
            row_bal = normalize_amount_cell(row[balance_idxs[0]])
        if not cell_looks_like_amount(row[ai]):
            picked = _pick_unclaimed(
                band=amount_band, search_ys=search_ys, prefer_y=row_y
            )
            if picked is not None:
                row[ai] = picked[0]
                _claim_picked(picked)
                claimed_pairs.add((picked[0], row_bal))
                amount_y = picked[2]
                amounts_n += 1
        else:
            norm = normalize_amount_cell(row[ai])
            # Balance co-location resolves repeated amounts; otherwise bind only
            # unclaimed glyphs so we do not steal an unclaimed spine.
            bound = _bind_known_amount(
                norm,
                bal=row_bal,
                search_ys=search_ys,
                prefer_y=row_y,
                allow_claimed=bool(row_bal),
            )
            if bound is None and row_bal:
                bound = _bind_known_amount(
                    norm,
                    bal=row_bal,
                    search_ys=(),
                    prefer_y=row_y,
                    allow_claimed=True,
                )
            if bound is not None:
                amount_y = bound[2]
                _claim_picked(bound)

        # Balance
        if balance_idxs and balance_band is not None:
            bi = balance_idxs[0]
            while len(row) <= bi:
                row.append("")
            if not cell_looks_like_amount(row[bi]):
                bal_ys = list(search_ys)
                if amount_y is not None:
                    bal_ys = [amount_y] + bal_ys
                picked_b = _pick_unclaimed(
                    band=balance_band,
                    search_ys=bal_ys,
                    prefer_y=amount_y if amount_y is not None else row_y,
                )
                if picked_b is not None:
                    row[bi] = picked_b[0]
                    _claim_picked(picked_b)
                    if cell_looks_like_amount(row[ai]):
                        claimed_pairs.add(
                            (normalize_amount_cell(row[ai]), picked_b[0])
                        )
                    balances_n += 1

        # Category / channel enrichment from amount spine line
        if text_idxs and amount_y is not None:
            ti = text_idxs[0]
            while len(row) <= ti:
                row.append("")
            channel = _channel_text_on_amount_line(
                words, amount_y=amount_y, text_band=text_band
            )
            if channel and (
                not row[ti]
                or (
                    channel.lower() not in normalize_text_cell(row[ti]).lower()
                    and _looks_like_body_only(row[ti])
                )
            ):
                merged = _merge_category(row[ti], channel, "")
                if merged and merged != normalize_text_cell(row[ti]):
                    row[ti] = merged
                    categories_n += 1

    # --- Pass 2: insert missing spines (amount+balance pairs not in matrix) ---
    spines = _spine_ops(money, amount_band, balance_band)
    inserts: List[Tuple[float, List[str]]] = []
    for amount, balance, y in spines:
        if balance_idxs and balance is None:
            continue
        pair = (amount, balance or "")
        if pair in claimed_pairs:
            continue
        # Skip if this exact money glyph was already used to fill a cell.
        amt_tok = next(
            (
                (t, x, yy)
                for t, x, yy in money
                if t == amount and abs(yy - y) <= _Y_LINE_TOL and _in_band(x, amount_band)
            ),
            None,
        )
        if amt_tok is None:
            # Amount token exists on spine Y but outside the learned amount band
            # (band too tight around left cluster). Still insert using spine Y.
            amt_tok = next(
                (
                    (t, x, yy)
                    for t, x, yy in money
                    if t == amount and abs(yy - y) <= _Y_LINE_TOL
                ),
                None,
            )
        if amt_tok and _money_id(*amt_tok) in claimed_money:
            continue

        new_row = _empty_row(ncols)
        if date_idxs:
            new_row[date_idxs[0]] = _date_on_line(words, y=y, x_hi=date_cut + 30.0)
        channel = _channel_text_on_amount_line(words, amount_y=y, text_band=text_band)
        body = _body_text_below(words, head_y=y, text_band=text_band)
        if text_idxs:
            new_row[text_idxs[0]] = _merge_category("", channel, body)
        new_row[amount_idxs[0]] = amount
        if balance_idxs and balance is not None:
            new_row[balance_idxs[0]] = balance
        claimed_pairs.add(pair)
        if amt_tok:
            _claim_picked(amt_tok)
        if balance is not None and balance_band is not None:
            for t, x, yy in money:
                if t == balance and abs(yy - y) <= _Y_LINE_TOL and _in_band(x, balance_band):
                    _claim_picked((t, x, yy))
                    break
        inserts.append((y, new_row))

    rows_inserted = 0
    if inserts:
        # Reading order: increasing y_top (from page top downward).
        positioned: List[Tuple[float, List[str]]] = []
        for idx, row in enumerate(working):
            y = row_ys[idx]
            if y is None:
                ai = amount_idxs[0]
                y_guess = float(idx) * 1000.0
                if ai < len(row) and cell_looks_like_amount(row[ai]):
                    norm = normalize_amount_cell(row[ai])
                    for text, _x, yy in money:
                        if text == norm and _in_band(_x, amount_band):
                            y_guess = yy
                            break
                y = y_guess
            positioned.append((float(y), row))
        positioned.extend(inserts)
        positioned.sort(key=lambda t: t[0])
        working = [r for _y, r in positioned]
        rows_inserted = len(inserts)

    stats = GeometryRecoverStats(
        amounts=amounts_n,
        balances=balances_n,
        categories=categories_n,
        rows_inserted=rows_inserted,
    )
    if stats.total:
        logger.info(
            "[table_amount_geometry_recover] recovered amounts=%s balances=%s "
            "categories=%s rows_inserted=%s",
            stats.amounts,
            stats.balances,
            stats.categories,
            stats.rows_inserted,
        )
    return working, stats


def recover_missing_amount_cells(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[Union[ColumnRole, str]],
    words: Sequence[PdfWord],
) -> Tuple[List[List[str]], int]:
    """
    Fill empty money cells and missing operation rows from page geometry.

    Returns (updated_matrix, total_recoveries) so callers can refresh warnings
    whenever anything was recovered. Prefer
    ``recover_operation_table_from_page_geometry`` when detailed stats are needed.
    """
    out, stats = recover_operation_table_from_page_geometry(
        columns, matrix, roles, words
    )
    return out, stats.total
