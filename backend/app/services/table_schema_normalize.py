"""
Normalize structured-table schemas for bank statements and similar registers.

Problem: Docling/markdown often turns a single visual header cell with two lines
(title + subtitle, footnotes ¹/²) into glued labels, splits one visual column into
two, or puts the subtitle row into data. Operations then shows phantom columns.

Contract (file-agnostic, not bank-specific):
  - one visual header cell → one column label
  - multi-line / title+subtitle cell → primary title as canonical name
  - footnote-only noise is not a column
  - Docling-split twin columns are merged back using header+content profiles
  - file-level schema locks after the first table; later pages do not re-learn headers
  - rows are classified (COMPLETE / OPEN_DESC / TAIL_FRAGMENT / META) and
    stitched by a completeness state machine into logical operations
  - packed dual-operations in one cell are exploded; shifted columns realigned by role
  - one canonical schema per file; later pages remap onto it by position/name
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_PIPE_ROW_SPLIT_RE = re.compile(r"(?<!\\)\|")
_MD_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_FOOTNOTE_MARK_RE = re.compile(
    r"(?:[¹²³⁴⁵⁶⁷⁸⁹₀-₉]+|(?<=\w)\d{1,2}(?=\s|$)|\[\d{1,2}\])"
)
_ONLY_FOOTNOTE_RE = re.compile(r"^[¹²³⁴⁵⁶⁷⁸⁹₀-₉\d\W_]{1,4}$")
_DATE_TOKEN_RE = re.compile(
    r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"
)
# Strict money: currency, sign at token start, thousands groups, or explicit decimals —
# never a bare digit glued inside a word ("обработки1", "LENTA-738") and never
# "MM NNN" sliced from "HH:MM AUTHCODE".
#
# Order matters: prefer full decimals / thousand-groups over a short signed prefix
# (otherwise "-1064.65" collapses to "-106").
_AMOUNT_TOKEN_RE = re.compile(
    r"(?:"
    r"(?<!\S)[+\-]\s*\d{1,3}(?:[\s\u00a0]\d{3})+(?:[.,]\d{1,2})?"
    r"|(?<!\S)[+\-]\s*\d+[.,]\d{1,2}"
    r"|(?<!\S)[+\-]\s*\d+"
    r"|(?<!\S)\d{1,3}(?:[\s\u00a0]\d{3})+(?:[.,]\d{1,2})?"
    r"|(?<!\S)\d+[.,]\d{1,2}"
    r")"
    r"(?:\s*(?:₽|руб\.?|RUB|USD|EUR))?",
    re.IGNORECASE,
)
_CURRENCY_RE = re.compile(r"[₽]|руб\.?|RUB|USD|EUR", re.IGNORECASE)
_TIME_RE = re.compile(r"^\d{1,2}[.:]\d{2}$")
_AUTH_CODE_RE = re.compile(r"^\d{4,8}$")
_DUP_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")
_SUBTITLE_CUE_RE = re.compile(
    r"(?i)описан|обработ|авторизац|валют|код\s|категор|остат|сумм|детал|назнач"
)
_DATE_HEADER_RE = re.compile(r"(?i)дата|date|время|time")
_AMOUNT_HEADER_RE = re.compile(r"(?i)сумм|amount|debit|credit|дебет|кредит")
_BALANCE_HEADER_RE = re.compile(r"(?i)остат|balance|сальдо")
_CATEGORY_HEADER_RE = re.compile(r"(?i)категор|category")
_DESCRIPTION_HEADER_RE = re.compile(
    r"(?i)описан|назнач|detail|merchant|контрагент|получател|плательщик"
)


@dataclass(frozen=True)
class ParsedPipeTable:
    columns: List[str]
    data_rows: List[List[str]]
    raw_header_cells: List[str]
    # Which raw cell index feeds each entry in `columns` (keeps alignment
    # when footnote-only columns are dropped). After repair(), indices are
    # identity into already-projected `data_rows`.
    value_indices: List[int] = field(default_factory=list)
    quality_score: float = 1.0
    quality_warnings: Tuple[str, ...] = ()
    column_roles: Tuple[str, ...] = ()


class ColumnRole(str, Enum):
    DATE = "date"
    AMOUNT = "amount"
    BALANCE = "balance"
    CATEGORY = "category"
    DESCRIPTION = "description"
    OTHER = "other"


@dataclass(frozen=True)
class _ColumnProfile:
    date_ratio: float
    time_ratio: float
    auth_ratio: float
    amount_ratio: float
    text_ratio: float
    empty_ratio: float
    avg_len: float


def _split_pipe_row(line: str) -> List[str]:
    inner = (line or "").strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [cell.strip() for cell in _PIPE_ROW_SPLIT_RE.split(inner)]


def _is_separator_line(line: str) -> bool:
    s = (line or "").strip()
    return bool(s) and "|" in s and bool(_MD_TABLE_SEP_RE.search(s))


def _is_pipe_line(line: str) -> bool:
    return "|" in (line or "")


def clean_cell_text(value: str) -> str:
    """Flatten HTML breaks / newlines and collapse whitespace."""
    text = _BR_RE.sub("\n", value or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFKC", text)
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return re.sub(r"\s+", " ", parts[0]).strip()
    return "\n".join(parts)


def strip_footnote_markers(value: str) -> str:
    text = _FOOTNOTE_MARK_RE.sub("", value or "")
    return re.sub(r"\s+", " ", text).strip(" ,;.-–—")


def is_noise_header_label(value: str) -> bool:
    label = strip_footnote_markers(clean_cell_text(value)).strip()
    if not label:
        return True
    if _ONLY_FOOTNOTE_RE.match(label):
        return True
    if re.fullmatch(r"\d{1,2}", label):
        return True
    if label in {"№", "#", "N", "n"}:
        return True
    return False


def cell_looks_like_amount(value: str) -> bool:
    """True for real money tokens; false for footnote digits / time+auth / SKUs."""
    flat = re.sub(r"\s+", " ", clean_cell_text(value).replace("\n", " ")).strip()
    if not flat:
        return False
    # Strip clock times and short auth codes so "21:07 535423" is not money.
    scrubbed = _TIME_RE.sub(" ", flat)
    scrubbed = re.sub(r"\b\d{1,2}[.:]\d{2}\b", " ", scrubbed)
    tokens = []
    for tok in scrubbed.split():
        if _AUTH_CODE_RE.match(tok):
            continue
        tokens.append(tok)
    scrubbed = " ".join(tokens).strip()
    if not scrubbed:
        return False
    if _CURRENCY_RE.search(scrubbed) and re.search(r"\d", scrubbed):
        return True
    return bool(_AMOUNT_TOKEN_RE.search(scrubbed))


def cell_looks_like_date(value: str) -> bool:
    return bool(_DATE_TOKEN_RE.search(clean_cell_text(value).replace("\n", " ")))


def _split_upper_title_from_subtitle(flat: str) -> Optional[str]:
    """
    'СУММА В ВАЛЮТЕ СЧЁТА Сумма В валюте' → 'СУММА В ВАЛЮТЕ СЧЁТА'.

    Only splits when a mostly-UPPERCASE token run is followed by a mixed/lower token.
    """
    parts = flat.split()
    if len(parts) < 2:
        return None
    for i, tok in enumerate(parts):
        if i == 0:
            continue
        letters = [ch for ch in tok if ch.isalpha()]
        if not letters or not any(ch.islower() for ch in letters):
            continue
        prev = "".join(parts[:i])
        prev_letters = [ch for ch in prev if ch.isalpha()]
        if len(prev_letters) < 3:
            continue
        upper_ratio = sum(1 for ch in prev_letters if ch.isupper()) / len(prev_letters)
        if upper_ratio >= 0.8:
            return " ".join(parts[:i])
    return None


def _prettify_allcaps_label(label: str) -> str:
    letters = [ch for ch in label if ch.isalpha()]
    if not letters:
        return label
    if sum(1 for ch in letters if ch.isupper()) / len(letters) < 0.85:
        return label
    out: List[str] = []
    for tok in label.split():
        core = tok.strip("()[]")
        # Keep short acronyms (МСК, USD, RUB), not full words like ДАТА.
        if core.isalpha() and core.isupper() and len(core) <= 3:
            out.append(tok)
            continue
        if (
            tok.startswith("(")
            and tok.endswith(")")
            and core.isupper()
            and len(core) <= 4
        ):
            out.append(tok)
            continue
        out.append(tok[:1].upper() + tok[1:].lower() if tok else tok)
    return " ".join(out)


def primary_header_label(value: str) -> str:
    """
    Canonical column name for one header cell.

    Multi-line cell → first non-empty line (title), footnotes stripped.
    ALL-CAPS title glued to mixed subtitle → title only.
    """
    cleaned = clean_cell_text(value)
    if not cleaned:
        return ""

    if "\n" in cleaned:
        primary = cleaned.split("\n", 1)[0].strip()
        primary = strip_footnote_markers(primary)
        split = _split_upper_title_from_subtitle(primary)
        return _prettify_allcaps_label(split or primary)

    flat = strip_footnote_markers(cleaned)
    split = _split_upper_title_from_subtitle(flat)
    if split:
        return _prettify_allcaps_label(split)
    return _prettify_allcaps_label(flat)


def looks_like_subtitle_row(cells: Sequence[str]) -> bool:
    """True when a row is header subtitles, not transaction data."""
    values = [clean_cell_text(c) for c in cells if clean_cell_text(c)]
    if len(values) < 2:
        return False
    if any(cell_looks_like_date(v) or cell_looks_like_amount(v) for v in values):
        return False
    subtitleish = 0
    for v in values:
        flat = strip_footnote_markers(v.replace("\n", " "))
        if len(flat) > 90:
            return False
        low = flat[:1].islower() if flat else False
        cue = bool(_SUBTITLE_CUE_RE.search(flat))
        if low or cue:
            subtitleish += 1
    return subtitleish >= max(2, (len(values) + 1) // 2)


def normalize_header_schema(
    raw_headers: Sequence[str],
) -> Tuple[List[str], List[int]]:
    """
    Normalize header cells → unique canonical labels.

    Returns (columns, value_indices) so dropped noise columns do not shift
    data cells onto the wrong labels.
    """
    out: List[str] = []
    indices: List[int] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_headers):
        label = primary_header_label(raw)
        if is_noise_header_label(label):
            continue
        key = label.casefold()
        if key in seen:
            n = 2
            while f"{label} ({n})".casefold() in seen:
                n += 1
            label = f"{label} ({n})"
            key = label.casefold()
        seen.add(key)
        out.append(label)
        indices.append(i)
    return out, indices


def _merge_header_rows(rows: Sequence[Sequence[str]]) -> List[str]:
    if not rows:
        return []
    width = max(len(r) for r in rows)
    merged: List[str] = []
    for i in range(width):
        parts: List[str] = []
        for row in rows:
            cell = row[i] if i < len(row) else ""
            cell = clean_cell_text(cell)
            if cell:
                parts.append(cell)
        merged.append("\n".join(parts))
    return merged


def _base_header_name(name: str) -> str:
    return _DUP_SUFFIX_RE.sub("", (name or "").strip())


def _join_cell_parts(*parts: str) -> str:
    cleaned: List[str] = []
    for part in parts:
        text = re.sub(r"\s*\n\s*", " ", clean_cell_text(part)).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return " ".join(cleaned)


def _profile_column(cells: Sequence[str]) -> _ColumnProfile:
    n = max(1, len(cells))
    date_n = time_n = auth_n = amount_n = text_n = empty_n = 0
    total_len = 0
    for raw in cells:
        cell = re.sub(r"\s*\n\s*", " ", clean_cell_text(raw)).strip()
        total_len += len(cell)
        if not cell:
            empty_n += 1
            continue
        if cell_looks_like_date(cell):
            date_n += 1
        if _TIME_RE.match(cell):
            time_n += 1
        elif _AUTH_CODE_RE.match(cell):
            auth_n += 1
        if cell_looks_like_amount(cell):
            amount_n += 1
        if len(cell) >= 8 and not cell_looks_like_amount(cell) and not _TIME_RE.match(cell):
            text_n += 1
    return _ColumnProfile(
        date_ratio=date_n / n,
        time_ratio=time_n / n,
        auth_ratio=auth_n / n,
        amount_ratio=amount_n / n,
        text_ratio=text_n / n,
        empty_ratio=empty_n / n,
        avg_len=total_len / n,
    )


def _name_similarity(a: str, b: str) -> float:
    x, y = a.casefold().strip(), b.casefold().strip()
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    if x in y or y in x:
        return 0.85
    tx, ty = set(re.findall(r"[a-zа-яё0-9]+", x, re.I)), set(
        re.findall(r"[a-zа-яё0-9]+", y, re.I)
    )
    if not tx or not ty:
        return 0.0
    return len(tx & ty) / max(len(tx), len(ty))


def _should_merge_adjacent_columns(
    left_name: str,
    right_name: str,
    left_cells: Sequence[str],
    right_cells: Sequence[str],
) -> bool:
    """
    Merge Docling-split twins of one visual column.

    Signals:
      - nearly identical headers (incl. 'Name' / 'Name (2)')
      - left mostly dates, right mostly times/auth codes
      - both date-named headers with complementary date vs time/auth profiles
    """
    if len(left_cells) < 2:
        return False
    base_l = _base_header_name(left_name)
    base_r = _base_header_name(right_name)
    same_name = base_l.casefold() == base_r.casefold()
    similar = _name_similarity(base_l, base_r) >= 0.9
    left_p = _profile_column(left_cells)
    right_p = _profile_column(right_cells)

    complementary_datetime = (
        left_p.date_ratio >= 0.35
        and (right_p.time_ratio + right_p.auth_ratio) >= 0.35
        and right_p.date_ratio < 0.35
    )
    date_named = bool(_DATE_HEADER_RE.search(base_l) and _DATE_HEADER_RE.search(base_r))

    if complementary_datetime and (same_name or similar or date_named):
        return True
    if same_name and right_p.avg_len <= 12 and left_p.date_ratio >= 0.3:
        if (right_p.time_ratio + right_p.auth_ratio + right_p.empty_ratio) >= 0.5:
            return True
    return False


def merge_phantom_columns(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
) -> Tuple[List[str], List[List[str]]]:
    """Collapse adjacent Docling phantom columns; preserve row alignment."""
    cols = list(columns)
    rows = [[str(c) for c in row] for row in matrix]
    if not cols or not rows:
        return cols, rows

    width = len(cols)
    for row in rows:
        if len(row) < width:
            row.extend([""] * (width - len(row)))
        elif len(row) > width:
            del row[width:]

    guard = 0
    while len(cols) >= 2 and guard < 16:
        guard += 1
        merged = False
        for i in range(len(cols) - 1):
            left_cells = [r[i] for r in rows]
            right_cells = [r[i + 1] for r in rows]
            if not _should_merge_adjacent_columns(
                cols[i], cols[i + 1], left_cells, right_cells
            ):
                continue
            cols[i] = _base_header_name(cols[i])
            for row in rows:
                row[i] = _join_cell_parts(row[i], row[i + 1])
                del row[i + 1]
            del cols[i + 1]
            merged = True
            break
        if not merged:
            break
    return cols, rows


def _header_role_hint(name: str) -> Optional[ColumnRole]:
    if _DATE_HEADER_RE.search(name):
        return ColumnRole.DATE
    if _BALANCE_HEADER_RE.search(name):
        return ColumnRole.BALANCE
    if _AMOUNT_HEADER_RE.search(name):
        return ColumnRole.AMOUNT
    if _CATEGORY_HEADER_RE.search(name):
        return ColumnRole.CATEGORY
    if _DESCRIPTION_HEADER_RE.search(name):
        return ColumnRole.DESCRIPTION
    return None


def infer_column_roles(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
) -> List[ColumnRole]:
    """Assign semantic roles from headers + content (bank-agnostic)."""
    roles: List[ColumnRole] = []
    used: set[ColumnRole] = set()
    profiles = []
    for i, _name in enumerate(columns):
        cells = [row[i] if i < len(row) else "" for row in matrix]
        profiles.append(_profile_column(cells))

    for i, name in enumerate(columns):
        hint = _header_role_hint(name)
        profile = profiles[i]
        role = ColumnRole.OTHER
        # Header hint wins over noisy content ratios (shifted/corrupt cells).
        if hint == ColumnRole.DATE:
            role = ColumnRole.DATE
        elif hint == ColumnRole.BALANCE:
            role = ColumnRole.BALANCE
        elif hint == ColumnRole.AMOUNT:
            role = ColumnRole.AMOUNT
        elif hint == ColumnRole.CATEGORY:
            role = ColumnRole.CATEGORY
        elif hint == ColumnRole.DESCRIPTION:
            role = ColumnRole.DESCRIPTION
        elif profile.date_ratio >= 0.4:
            role = ColumnRole.DATE
        elif profile.amount_ratio >= 0.3 and "остат" in name.casefold():
            role = ColumnRole.BALANCE
        elif profile.amount_ratio >= 0.35:
            role = ColumnRole.AMOUNT
        elif profile.text_ratio >= 0.45:
            role = ColumnRole.DESCRIPTION
        if role in used and role != ColumnRole.OTHER:
            if role == ColumnRole.DATE:
                pass
            elif role == ColumnRole.AMOUNT and ColumnRole.BALANCE not in used:
                role = (
                    ColumnRole.BALANCE
                    if _BALANCE_HEADER_RE.search(name)
                    else ColumnRole.OTHER
                )
            else:
                role = ColumnRole.OTHER
        if role != ColumnRole.OTHER:
            used.add(role)
        roles.append(role)
    return roles


# Truncation of a multi-line description split across PDF page / table rows.
_TRUNCATED_TEXT_SUFFIX_RE = re.compile(
    r"(?i)(?:\bпо\s*$|операци(?:я|и)\s+по\s*$|\*{1,4}\s*$|,\s*$|\bдля\s*$|\bот\s*$|"
    r"по\s+сч[её]ту\s*$|по\s+карте\s*$)"
)
# Completed operation marker (card or account) — rest often starts the next op.
_CARD_OP_COMPLETE_RE = re.compile(
    r"(?i)операци(?:я|и)\s+по\s+(?:карте|сч[её]ту)(?:\s*\*+\s*\d*)?"
)
# Continuation / orphan tails produced by layout split (bank-agnostic).
_DESC_TAIL_RE = re.compile(
    r"(?i)^(?:"
    r"карте(?:\s*\*+\s*\d*)?"
    r"|сч[её]ту(?:\s*\*+\s*\d*)?"
    r"|\*+\s*\d+"
    r"|карте\s+\*+\s*\d+"
    r")$"
)
# Channel / verb heads that may include Latin tokens (QR, SBP) — structural short labels.
_CATEGORY_HEAD_ONLY_RE = re.compile(
    r"(?i)^(?:"
    r"перевод(?:\s+на\s+карту|\s+с\s+карты|\s+сбп)?"
    r"|оплата(?:\s+по\s+qr[- ]?коду(?:\s+сбп)?)?"
    r"|наличные|выдача\s+наличных"
    r"|покупка|снятие"
    r")$"
)
# New operation category/verb glued after a completed op inside one cell.
_GLUED_NEXT_OP_RE = re.compile(
    r"(?i)\s+(?="
    r"перевод|покупка|снятие|выдача|оплата|супермаркет|"
    r"ресторан|транспорт|прочие|отдых|путешеств|коммунальн|"
    r"одежда|кафе|наличные|сервис"
    r")"
)


class RowKind(str, Enum):
    """Completeness of one logical operation row after Docling export."""

    COMPLETE = "complete"
    OPEN_DESC = "open_desc"  # description truncated; needs a tail
    TAIL_FRAGMENT = "tail_fragment"  # orphan suffix of previous description
    META = "meta"  # time/auth-only continuation (classic multi-line date cell)


@dataclass(frozen=True)
class _RowView:
    kind: RowKind
    text: str
    date_token: str
    has_amount: bool
    has_balance: bool
    has_auth_or_time: bool


def normalize_date_cell(value: str) -> str:
    """
    Canonical date/datetime cell: dedupe repeated dates, keep date + time/auth.

    '11.02.2025 11.02.2025 11.02.2025' → '11.02.2025'
    '10.07.2026 19.28 887717' → '10.07.2026 19.28 887717'
    """
    flat = re.sub(r"\s+", " ", clean_cell_text(value).replace("\n", " ")).strip()
    if not flat:
        return ""

    dates = _DATE_TOKEN_RE.findall(flat)
    if not dates:
        return flat

    unique_dates: List[str] = []
    for d in dates:
        if d not in unique_dates:
            unique_dates.append(d)

    tokens = flat.split()
    times = [t for t in tokens if _TIME_RE.match(t)]
    auth_codes = [t for t in tokens if _AUTH_CODE_RE.match(t)]

    if len(unique_dates) == 1:
        parts = [unique_dates[0]]
        if times:
            parts.append(times[0])
        if auth_codes:
            parts.append(auth_codes[0])
        return " ".join(parts)

    if len(unique_dates) == 2:
        # Operation date + processing date (or twin layout cols): keep the first
        # calendar day + time/auth. Exposing two dates as one cell is not a
        # single operation timestamp.
        parts = [unique_dates[0]]
        if times:
            parts.append(times[0])
        if auth_codes and auth_codes[0] not in parts:
            parts.append(auth_codes[0])
        return " ".join(parts)

    return " ".join(unique_dates[:1] + (times[:1] if times else []))


def normalize_amount_cell(value: str) -> str:
    """Single canonical money token from a cell (RU grouping preserved)."""
    flat = re.sub(r"\s+", " ", clean_cell_text(value).replace("\n", " ")).strip()
    if not flat or flat in {"-", "—", "–"}:
        return flat
    match = _AMOUNT_TOKEN_RE.search(flat.replace("\u2212", "-"))
    if match:
        return match.group(0).strip()
    return flat


def normalize_text_cell(value: str) -> str:
    return re.sub(r"\s+", " ", clean_cell_text(value).replace("\n", " ")).strip()


def normalize_cell_by_role(value: str, role: ColumnRole) -> str:
    if role == ColumnRole.DATE:
        return normalize_date_cell(value)
    if role in (ColumnRole.AMOUNT, ColumnRole.BALANCE):
        return normalize_amount_cell(value)
    if role in (ColumnRole.CATEGORY, ColumnRole.DESCRIPTION, ColumnRole.OTHER):
        return normalize_text_cell(value)
    return clean_cell_text(value)


def normalize_matrix_cells(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[ColumnRole],
) -> List[List[str]]:
    out: List[List[str]] = []
    for row in matrix:
        normalized: List[str] = []
        for col_i in range(len(columns)):
            raw = row[col_i] if col_i < len(row) else ""
            role = roles[col_i] if col_i < len(roles) else ColumnRole.OTHER
            normalized.append(normalize_cell_by_role(raw, role))
        out.append(normalized)
    return out


def _first_date_token(value: str) -> str:
    match = _DATE_TOKEN_RE.search(clean_cell_text(value).replace("\n", " "))
    return match.group(0) if match else ""


def _text_column_indices(roles: Sequence[ColumnRole]) -> List[int]:
    """Description-bearing columns only — never recycle leftover OTHER (e.g. 2nd date)."""
    preferred = [
        i
        for i, r in enumerate(roles)
        if r in (ColumnRole.CATEGORY, ColumnRole.DESCRIPTION)
    ]
    if preferred:
        return preferred
    return [i for i, r in enumerate(roles) if r == ColumnRole.OTHER]


def _row_has_amount(row: Sequence[str], amount_idxs: Sequence[int]) -> bool:
    return any(
        cell_looks_like_amount(row[i])
        for i in amount_idxs
        if i < len(row) and clean_cell_text(row[i]).strip()
    )


def _row_text(row: Sequence[str], text_idxs: Sequence[int]) -> str:
    parts: List[str] = []
    for i in text_idxs:
        if i >= len(row):
            continue
        cell = normalize_text_cell(row[i])
        if cell:
            parts.append(cell)
    return " ".join(parts)


def _is_category_or_channel_head_only(text: str) -> bool:
    """
    True when the description is only a short taxonomy/channel label and the
    merchant / body spilled to the next layout row.

    Structural (length / script / completeness) — not a bank category dictionary.
    """
    flat = normalize_text_cell(text)
    if not flat:
        return False
    if _CARD_OP_COMPLETE_RE.search(flat) or cell_looks_like_amount(flat):
        return False
    if _CATEGORY_HEAD_ONLY_RE.match(flat):
        return True
    if len(flat) > 56 or len(flat.split()) > 5:
        return False
    if flat[:1].islower():
        return False
    # Latin merchant / SKU ⇒ not a bare category head.
    if re.search(r"[A-Za-z]{2,}", flat):
        return False
    if re.search(r"(?i)\b(операци|карте|сч[её]ту|\*{2,})\b", flat):
        return False
    return bool(re.fullmatch(r"[А-Яа-яЁё0-9\s\-,./]+", flat))


def _is_thin_operation_head(text: str) -> bool:
    """
    Short channel/category head waiting for a merchant / body row.

    Allows minor Latin typos inside RU heads ("Перевод c карты") without
    treating a completed card/account op or a merchant line as a head.
    """
    if _is_category_or_channel_head_only(text):
        return True
    flat = normalize_text_cell(text)
    if not flat or _CARD_OP_COMPLETE_RE.search(flat) or cell_looks_like_amount(flat):
        return False
    if len(flat) > 56 or len(flat.split()) > 5:
        return False
    # Merchant lines are Latin-heavy; thin heads stay mostly Cyrillic.
    if len(re.findall(r"[A-Za-z]", flat)) >= 3:
        return False
    return bool(
        re.match(
            r"(?i)^(перевод|покупка|оплата|снятие|выдача|прочие|супермаркет|"
            r"ресторан|транспорт|отдых|путешеств|коммунальн|одежда|наличн|сервис)",
            flat,
        )
    )


def _is_desc_truncated(text: str) -> bool:
    if not text:
        return False
    if _is_thin_operation_head(text):
        return True
    if _TRUNCATED_TEXT_SUFFIX_RE.search(text):
        return True
    return bool(re.search(r"(?i)операци(?:я|и)\s+по\s*$", text))


def _is_desc_tail_fragment(text: str) -> bool:
    if not text:
        return False
    flat = normalize_text_cell(text)
    if _DESC_TAIL_RE.match(flat):
        return True
    if _is_merchant_continuation(flat):
        return True
    # Short leftover without a category-like head (≤5 tokens, ≤40 chars).
    if len(flat) <= 40 and len(flat.split()) <= 5:
        if flat[:1].islower() or flat.startswith(("*", "«", "„")):
            return True
        if re.match(r"(?i)^(карте|карты|счёта|счета|счету)\b", flat):
            return True
    return False


def _is_transfer_attribution_body(text: str) -> bool:
    """
    Incoming-transfer attribution line (who sent funds), not a new channel head.

    Typical multi-line layout:
      «Перевод на карту» + amount + balance
      «Перевод от И. Имя. Операция по карте ****…»  ← same op body
    """
    flat = normalize_text_cell(text)
    if not flat:
        return False
    return bool(re.match(r"(?i)^перевод\s+от\b", flat))


def _is_merchant_continuation(text: str) -> bool:
    """
    Merchant / mid-description fragment that is not a fresh category-headed op.

    Used when a category/channel head and the merchant line split across rows.
    Texts that start with a channel/category verb are treated as independent
    operation heads (see ``_is_amount_on_open_head_split`` for the case where
    money landed on a thin head and the completed body is the next row).
    """
    flat = normalize_text_cell(text)
    if not flat or _is_thin_operation_head(flat):
        return False
    # Attribution body of an incoming transfer — continue the thin «Перевод…» head.
    if _is_transfer_attribution_body(flat):
        return True
    # Fresh op starting with a category/verb is not a merchant spill.
    if _GLUED_NEXT_OP_RE.match(" " + flat):
        return False
    if re.match(r"^[A-Za-z0-9*«\"„]", flat):
        return True
    if re.search(r"(?i)\bRUS\b", flat) or _CARD_OP_COMPLETE_RE.search(flat):
        return True
    # Cyrillic merchant body without a leading category cue.
    if flat[:1].isupper() and len(flat) >= 8 and " " in flat:
        return True
    return False


def _is_standalone_channel_complete_op(text: str) -> bool:
    """
    Full op already carrying its own channel head + merchant + card/account marker.

    Used to refuse stitching a thin head onto an independent sibling row
    (e.g. thin QR + «Супермаркеты MAGAZIN… Операция по карте»).
    Merchant-only bodies («Сервисы Яндекса. Операция по карте», «RE. Операция…»)
    and transfer attribution («Перевод от …») do not match.
    """
    flat = normalize_text_cell(text)
    if not flat or not _CARD_OP_COMPLETE_RE.search(flat):
        return False
    if _is_thin_operation_head(flat):
        return False
    if _is_transfer_attribution_body(flat):
        return False
    return bool(
        re.match(
            r"(?i)^(оплата|перевод|покупка|снятие|выдача|прочие\s+операц|"
            r"супермаркет|ресторан|транспорт|наличн)",
            flat,
        )
    )


def _is_amount_on_open_head_split(primary: _RowView, nxt: _RowView) -> bool:
    """
    Docling split: money lands on a thin channel/category OPEN head; the completed
    operation *body* (merchant + card/account marker) is the next row without money.

    Typical bank multi-line cell:
      «Оплата по QR-коду СБП» + amount
      «Сервисы Яндекса. Операция по карте ****…»   ← merchant body, same op

    Never stitches onto a sibling that already has its own channel head
    (QR head + «Супермаркеты MAGAZIN…»).
    """
    if not primary.has_amount or nxt.has_amount:
        return False
    if _CARD_OP_COMPLETE_RE.search(primary.text or ""):
        return False
    if not (
        primary.kind == RowKind.OPEN_DESC or _is_thin_operation_head(primary.text)
    ):
        return False
    if not _CARD_OP_COMPLETE_RE.search(nxt.text or ""):
        return False
    if _is_standalone_channel_complete_op(nxt.text or ""):
        return False
    # Latin / merchant spill, or Cyrillic merchant noun-phrase + card marker.
    if _is_merchant_continuation(nxt.text):
        return True
    flat = normalize_text_cell(nxt.text or "")
    # Card-complete body that is not a channel-headed sibling (Сервисы Яндекса…).
    return bool(flat) and not _is_thin_operation_head(flat)


def _thin_head_text_is_prefix_of_body(head: str, body: str) -> bool:
    """True when thin category cue is already inside the merchant/body text."""
    h = normalize_text_cell(head).casefold()
    b = normalize_text_cell(body).casefold()
    if not h or not b or len(h) < 4:
        return False
    return b.startswith(h) or h in b


def _is_body_then_amount_on_thin_head(primary: _RowView, nxt: _RowView) -> bool:
    """
    Reverse Docling split: merchant/body row first (no money), thin category head
    carrying amount+balance next — often with a mis-stamped calendar day.

    Layout reading order sometimes emits the body before the amount spine row.
    """
    if primary.has_amount or not nxt.has_amount:
        return False
    if not _is_thin_operation_head(nxt.text):
        return False
    body = primary.text or ""
    if not body or len(body) < 8:
        return False
    # Body must look like a real op description (card/account marker or merchant).
    if not (
        _CARD_OP_COMPLETE_RE.search(body)
        or _is_merchant_continuation(body)
        or re.search(r"(?i)\bRUS\b", body)
    ):
        return False
    # Thin head must be the category cue already present on the body
    # (not an unrelated next operation).
    return _thin_head_text_is_prefix_of_body(nxt.text or "", body)


def _date_cell_is_meta_only(value: str) -> bool:
    flat = normalize_text_cell(value)
    if not flat:
        return False
    if _first_date_token(flat):
        return False
    tokens = flat.split()
    return all(_TIME_RE.match(t) or _AUTH_CODE_RE.match(t) for t in tokens)


def _split_glued_operation_text(text: str) -> Optional[Tuple[str, str]]:
    """
    Split one cell that contains the end of op A and the start of op B.

    Uses the *first* completed card/account-op marker followed by a new
    operation head — not the last (multi-op cells would otherwise stay glued).
    """
    flat = normalize_text_cell(text)
    if not flat:
        return None
    for match in _CARD_OP_COMPLETE_RE.finditer(flat):
        end = match.end()
        rest = flat[end:].strip()
        # Allow short category heads ("Супермаркеты") as the next-op spill.
        if len(rest) < 4:
            continue
        if not _GLUED_NEXT_OP_RE.match(" " + rest):
            continue
        head = flat[:end].strip()
        if len(head) < 12:
            continue
        return head, rest
    return None


def classify_operation_row(
    row: Sequence[str],
    *,
    date_idxs: Sequence[int],
    amount_idxs: Sequence[int],
    balance_idxs: Sequence[int],
    text_idxs: Sequence[int],
) -> _RowView:
    text = _row_text(row, text_idxs)
    date_raw = ""
    if date_idxs and date_idxs[0] < len(row):
        date_raw = row[date_idxs[0]]
    date_token = _first_date_token(date_raw)
    has_amount = _row_has_amount(row, amount_idxs)
    has_balance = _row_has_amount(row, balance_idxs)
    has_auth_or_time = False
    if date_raw:
        toks = normalize_text_cell(date_raw).split()
        has_auth_or_time = any(
            _TIME_RE.match(t) or _AUTH_CODE_RE.match(t) for t in toks
        )

    if _is_desc_tail_fragment(text):
        kind = RowKind.TAIL_FRAGMENT
    elif _is_desc_truncated(text):
        kind = RowKind.OPEN_DESC
    elif (
        not text
        and not has_amount
        and (has_auth_or_time or _date_cell_is_meta_only(date_raw))
    ):
        kind = RowKind.META
    elif not text and not has_amount and has_balance and has_auth_or_time:
        kind = RowKind.META
    elif (
        not has_amount
        and has_auth_or_time
        and text
        and not date_token
        and _date_cell_is_meta_only(date_raw)
    ):
        # Continuation row that carries description + auth/time, no own date.
        kind = RowKind.META
    else:
        kind = RowKind.COMPLETE

    return _RowView(
        kind=kind,
        text=text,
        date_token=date_token,
        has_amount=has_amount,
        has_balance=has_balance,
        has_auth_or_time=has_auth_or_time,
    )


def _dates_compatible(primary: _RowView, nxt: _RowView) -> bool:
    # Layout splits sometimes mis-stamp the calendar day on one of the two rows.
    if _is_amount_on_open_head_split(primary, nxt):
        return True
    if _is_body_then_amount_on_thin_head(primary, nxt):
        return True
    # OPEN / card-mask / merchant spill: layout often stamped a neighboring date.
    if nxt.kind == RowKind.TAIL_FRAGMENT and (
        primary.kind == RowKind.OPEN_DESC
        or _DESC_TAIL_RE.match(nxt.text or "")
        or _is_merchant_continuation(nxt.text or "")
    ):
        return True
    if primary.kind == RowKind.OPEN_DESC and _is_merchant_continuation(nxt.text or ""):
        return True
    if not primary.date_token or not nxt.date_token:
        return True
    if primary.date_token == nxt.date_token:
        return True
    # Processing date may differ from operation date when next carries auth/time.
    return nxt.has_auth_or_time


def _compose_description(head: str, tail: str) -> str:
    """Join description parts; restore 'Операция по' when only 'карте/счёту…' remained."""
    h = normalize_text_cell(head)
    t = normalize_text_cell(tail)
    if not h:
        return t
    if not t:
        return h
    # Body already contains the thin category cue — do not append a duplicate head.
    if _thin_head_text_is_prefix_of_body(t, h):
        return h
    if _thin_head_text_is_prefix_of_body(h, t):
        return t
    if _DESC_TAIL_RE.match(t) and not re.search(
        r"(?i)операци\w*\s+по\s+(?:карте|сч[её]ту)", h
    ):
        if re.search(r"(?i)\bпо\s*$", h):
            return normalize_text_cell(f"{h} {t}")
        return normalize_text_cell(f"{h} Операция по {t}")
    return normalize_text_cell(f"{h} {t}")


def _merge_operation_rows(
    columns: Sequence[str],
    primary: Sequence[str],
    nxt: Sequence[str],
    *,
    money_idxs: Sequence[int],
    amount_idxs: Sequence[int],
    balance_idxs: Sequence[int],
    text_idxs: Sequence[int],
    date_idxs: Sequence[int],
) -> List[str]:
    merged: List[str] = []
    primary_text = _row_text(primary, text_idxs)
    next_text = _row_text(nxt, text_idxs)
    composed = _compose_description(primary_text, next_text) if text_idxs else ""
    text_written = False
    nxt_has_amount = _row_has_amount(nxt, amount_idxs)
    for col_i in range(len(columns)):
        a = primary[col_i] if col_i < len(primary) else ""
        b = nxt[col_i] if col_i < len(nxt) else ""
        if col_i in amount_idxs:
            merged.append(a if clean_cell_text(a).strip() else b)
        elif col_i in balance_idxs:
            # Prefer primary balance. Take nxt balance only when it belongs to the
            # continuation (amount on tail / mask-only tail). Skip phantom balances
            # pasted onto transfer-attribution bodies (statement opening remainder).
            a_flat = clean_cell_text(a).strip()
            b_flat = clean_cell_text(b).strip()
            if a_flat:
                merged.append(a)
            elif not b_flat:
                merged.append("")
            elif nxt_has_amount:
                merged.append(b)
            elif _is_desc_tail_fragment(next_text):
                merged.append(b)
            elif _is_transfer_attribution_body(next_text):
                merged.append("")
            else:
                merged.append(b)
        elif col_i in money_idxs:
            merged.append(a if clean_cell_text(a).strip() else b)
        elif col_i in date_idxs:
            a_flat = clean_cell_text(a).strip()
            b_flat = clean_cell_text(b).strip()
            if not a_flat:
                merged.append(b)
            elif not b_flat:
                merged.append(a)
            elif _date_cell_is_meta_only(b_flat):
                merged.append(_join_cell_parts(a_flat, b_flat))
            else:
                d0 = _first_date_token(a_flat)
                d1 = _first_date_token(b_flat)
                # Same calendar day: fold time/auth from the continuation cell.
                if d0 and d1 and d0 == d1:
                    merged.append(_join_cell_parts(a_flat, b_flat))
                else:
                    merged.append(a_flat)
        elif col_i in text_idxs:
            if not text_written:
                merged.append(composed)
                text_written = True
            else:
                merged.append("")
        else:
            merged.append(_join_cell_parts(a, b))
    return merged


def _set_row_text(
    row: List[str],
    text_idxs: Sequence[int],
    text: str,
) -> None:
    if not text_idxs:
        return
    row[text_idxs[0]] = text
    for i in text_idxs[1:]:
        if i < len(row):
            row[i] = ""


def explode_packed_operations(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[ColumnRole],
) -> List[List[str]]:
    """
    One description cell → one logical operation.

    When Docling packs op B into op A's cell after a completed card-op marker,
    emit two rows. Amount/balance stay on the first completed op; the spilled
    op is emitted without inventing money (better than a contaminated label).
    """
    del columns
    text_idxs = _text_column_indices(roles)
    money_idxs = [
        i for i, r in enumerate(roles) if r in (ColumnRole.AMOUNT, ColumnRole.BALANCE)
    ]
    if not text_idxs:
        return [list(r) for r in matrix]

    out: List[List[str]] = []
    for row in matrix:
        base = [str(c) for c in row]
        text = _row_text(base, text_idxs)
        pieces: List[str] = []
        remaining = text
        while remaining:
            split = _split_glued_operation_text(remaining)
            if not split:
                pieces.append(remaining)
                break
            head, rest = split
            pieces.append(head)
            remaining = rest
        if len(pieces) <= 1:
            out.append(base)
            continue
        for pi, piece in enumerate(pieces):
            new_row = list(base)
            _set_row_text(new_row, text_idxs, piece)
            if pi > 0:
                for mi in money_idxs:
                    if mi < len(new_row):
                        new_row[mi] = ""
            out.append(new_row)
    return out


def unglue_packed_rows(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[ColumnRole],
) -> List[List[str]]:
    """
    When a TAIL_FRAGMENT follows a packed primary, move the glued next-op head
    onto that tail row (keeps amount on the continuation when Docling put it there).
    """
    del columns
    text_idxs = _text_column_indices(roles)
    date_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.DATE]
    amount_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.AMOUNT]
    balance_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.BALANCE]
    if not text_idxs or len(matrix) < 2:
        return [list(r) for r in matrix]

    rows = [[str(c) for c in row] for row in matrix]
    i = 0
    out: List[List[str]] = []
    while i < len(rows):
        if i + 1 >= len(rows):
            out.append(list(rows[i]))
            break
        primary = classify_operation_row(
            rows[i],
            date_idxs=date_idxs,
            amount_idxs=amount_idxs,
            balance_idxs=balance_idxs,
            text_idxs=text_idxs,
        )
        nxt = classify_operation_row(
            rows[i + 1],
            date_idxs=date_idxs,
            amount_idxs=amount_idxs,
            balance_idxs=balance_idxs,
            text_idxs=text_idxs,
        )
        if nxt.kind == RowKind.TAIL_FRAGMENT or (
            _is_merchant_continuation(nxt.text) and not nxt.has_amount
        ):
            split = _split_glued_operation_text(primary.text)
            if split:
                head, rest = split
                left = list(rows[i])
                right = list(rows[i + 1])
                _set_row_text(left, text_idxs, head)
                _set_row_text(right, text_idxs, _compose_description(rest, nxt.text))
                out.append(left)
                out.append(right)
                i += 2
                continue
        out.append(list(rows[i]))
        i += 1
    return out


def realign_shifted_rows(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[ColumnRole],
) -> List[List[str]]:
    """
    Fix classic Docling column shifts using role expectations:

      - amount cell holds long description text
      - category/description cell holds time/auth only
    → move meta into DATE, description into text role, clear bogus amount.
    """
    del columns
    date_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.DATE]
    amount_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.AMOUNT]
    text_idxs = _text_column_indices(roles)
    if not amount_idxs or not text_idxs:
        return [list(r) for r in matrix]

    amount_i = amount_idxs[0]
    text_i = text_idxs[0]
    date_i = date_idxs[0] if date_idxs else None
    out: List[List[str]] = []
    for raw in matrix:
        row = [str(c) for c in raw]
        while len(row) <= max(amount_i, text_i, date_i or 0):
            row.append("")
        amount_cell = normalize_text_cell(row[amount_i])
        text_cell = normalize_text_cell(row[text_i])
        amount_is_text = bool(amount_cell) and not cell_looks_like_amount(amount_cell) and (
            len(amount_cell) >= 12 or bool(_CARD_OP_COMPLETE_RE.search(amount_cell))
        )
        text_is_meta = bool(text_cell) and (
            _date_cell_is_meta_only(text_cell)
            or (
                not _first_date_token(text_cell)
                and all(
                    _TIME_RE.match(t) or _AUTH_CODE_RE.match(t) for t in text_cell.split()
                )
            )
        )
        if amount_is_text and text_is_meta:
            if date_i is not None:
                row[date_i] = _join_cell_parts(row[date_i], text_cell)
            row[text_i] = amount_cell
            row[amount_i] = ""
        elif amount_is_text and (not text_cell or _DESC_TAIL_RE.match(text_cell)):
            # Description landed in amount; category empty / mask only.
            if text_cell and _DESC_TAIL_RE.match(text_cell):
                row[text_i] = _compose_description(amount_cell, text_cell)
            else:
                row[text_i] = amount_cell
            row[amount_i] = ""
        out.append(row)
    return out


def looks_like_table_header_echo_row(cells: Sequence[str]) -> bool:
    """
    Docling sometimes re-emits column titles as a data row mid-statement.

    Typical cues (any language mix): «и код авторизации», «Описание операции»,
    «Сумма в валюте операции» — often with a stray money glyph from the grid.
    """
    values = [clean_cell_text(c) for c in cells if clean_cell_text(c)]
    if len(values) < 2:
        return False
    joined = " ".join(values).casefold()
    cues = 0
    if re.search(r"авторизац", joined):
        cues += 1
    if re.search(r"описани\w*\s+операц", joined):
        cues += 1
    if re.search(r"сумм\w*\s+в\s+валют", joined):
        cues += 1
    if re.search(r"\bкод\s+авторизац", joined):
        cues += 1
    # Strong single cue in the date-like first cell is enough when another
    # header noun appears anywhere.
    if cues >= 2:
        return True
    first = values[0].casefold()
    if "авторизац" in first and any(
        _SUBTITLE_CUE_RE.search(v) for v in values[1:]
    ):
        return True
    return False


def looks_like_repeated_header_row(
    cells: Sequence[str],
    canonical_columns: Sequence[str],
) -> bool:
    """True when a data row is a repeated page header / subtitle, not an operation."""
    if looks_like_subtitle_row(cells):
        return True
    if looks_like_table_header_echo_row(cells):
        return True
    values = [clean_cell_text(c) for c in cells]
    if not any(values):
        return False
    if any(cell_looks_like_date(v) or cell_looks_like_amount(v) for v in values if v):
        return False
    hits = 0
    for cell in values:
        if not cell:
            continue
        label = primary_header_label(cell) or cell
        if any(_name_similarity(label, c) >= 0.72 for c in canonical_columns):
            hits += 1
        elif _SUBTITLE_CUE_RE.search(cell):
            hits += 1
    need = max(2, (len(canonical_columns) + 1) // 2)
    return hits >= need


def drop_repeated_header_rows(
    matrix: Sequence[Sequence[str]],
    canonical_columns: Sequence[str],
) -> List[List[str]]:
    if not canonical_columns:
        return [list(r) for r in matrix]
    return [
        list(row)
        for row in matrix
        if not looks_like_repeated_header_row(row, canonical_columns)
    ]


def can_stitch_operation_rows(primary: _RowView, nxt: _RowView) -> bool:
    """
    Decide whether nxt continues primary as one logical operation.

    Contract:
      OPEN_DESC + TAIL_FRAGMENT → stitch (even if amount landed on the tail)
      OPEN thin head with amount + completed body without amount → stitch
      OPEN_DESC / COMPLETE + META → stitch (auth/time or multi-line cell)
      COMPLETE + TAIL_FRAGMENT → stitch when primary is truncated or tail is
        a pure card-op suffix
      COMPLETE + descriptive row without amount → stitch when dates align and
        next carries auth/time or primary is open (Docling multi-line cells)
    """
    if not _dates_compatible(primary, nxt):
        return False

    if nxt.kind == RowKind.META:
        return primary.kind in (RowKind.OPEN_DESC, RowKind.COMPLETE)

    if _is_amount_on_open_head_split(primary, nxt):
        return True

    # Body/merchant first (no money), thin category head with money next.
    if _is_body_then_amount_on_thin_head(primary, nxt):
        return True

    if nxt.kind == RowKind.TAIL_FRAGMENT:
        if primary.kind == RowKind.OPEN_DESC:
            return True
        if primary.kind == RowKind.COMPLETE:
            if _DESC_TAIL_RE.match(nxt.text or ""):
                return True
            if _is_merchant_continuation(nxt.text) and (
                _is_desc_truncated(primary.text)
                or _is_thin_operation_head(primary.text)
            ):
                return True
        return False

    # Category/channel head + merchant body classified COMPLETE (has amount).
    if primary.kind == RowKind.OPEN_DESC and _is_thin_operation_head(primary.text):
        if _is_merchant_continuation(nxt.text):
            return True

    if nxt.has_amount:
        return False

    if not nxt.text or len(nxt.text) < 6:
        return False

    # Independent operation head (e.g. after explode_packed_operations) — never re-merge.
    if _GLUED_NEXT_OP_RE.match(" " + nxt.text):
        return False

    if primary.kind == RowKind.OPEN_DESC:
        # Do not glue a finished open-looking head onto the next independent op head.
        if _is_thin_operation_head(nxt.text):
            return False
        # Multi-line spill of an incomplete op (same day / auth-only next).
        if nxt.has_auth_or_time or not nxt.date_token:
            return True
        if primary.date_token and primary.date_token == nxt.date_token:
            return True
        return True

    return False


def stitch_continuation_rows(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Optional[Sequence[ColumnRole]] = None,
) -> List[List[str]]:
    """
    State-machine stitch of Docling-split operation rows into logical ops.

    Not bank-specific: uses column roles + row completeness kinds.
    """
    if len(matrix) < 2:
        return [list(r) for r in matrix]

    role_list = list(roles) if roles is not None else infer_column_roles(columns, matrix)
    date_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.DATE]
    amount_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.AMOUNT]
    balance_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.BALANCE]
    money_idxs = list(dict.fromkeys([*amount_idxs, *balance_idxs]))
    text_idxs = _text_column_indices(role_list)

    out: List[List[str]] = []
    i = 0
    rows = [[str(c) for c in row] for row in matrix]
    while i < len(rows):
        current = list(rows[i])
        j = i + 1
        # Greedy chain: OPEN head + merchant + mask tails may span >2 layout rows.
        while j < len(rows):
            primary_view = classify_operation_row(
                current,
                date_idxs=date_idxs,
                amount_idxs=amount_idxs,
                balance_idxs=balance_idxs,
                text_idxs=text_idxs,
            )
            next_view = classify_operation_row(
                rows[j],
                date_idxs=date_idxs,
                amount_idxs=amount_idxs,
                balance_idxs=balance_idxs,
                text_idxs=text_idxs,
            )
            if not can_stitch_operation_rows(primary_view, next_view):
                break
            current = _merge_operation_rows(
                columns,
                current,
                rows[j],
                money_idxs=money_idxs,
                amount_idxs=amount_idxs,
                balance_idxs=balance_idxs,
                text_idxs=text_idxs,
                date_idxs=date_idxs,
            )
            j += 1
        out.append(current)
        i = j
    return out


def drop_orphan_fragment_rows(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Sequence[ColumnRole],
) -> List[List[str]]:
    """
    Quality gate: drop residual fragments that still carry no amount after stitch
    (pure layout leftovers / bare category heads / attribution bodies that
    Docling kept as separate rows with a phantom balance).
    """
    del columns
    date_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.DATE]
    amount_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.AMOUNT]
    balance_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.BALANCE]
    text_idxs = _text_column_indices(roles)
    if not text_idxs:
        return [list(r) for r in matrix]

    kept: List[List[str]] = []
    for row in matrix:
        if looks_like_table_header_echo_row(row):
            continue
        view = classify_operation_row(
            row,
            date_idxs=date_idxs,
            amount_idxs=amount_idxs,
            balance_idxs=balance_idxs,
            text_idxs=text_idxs,
        )
        if view.kind == RowKind.TAIL_FRAGMENT and not view.has_amount and not view.has_balance:
            continue
        if (
            not view.has_amount
            and not view.has_balance
            and _is_thin_operation_head(view.text)
        ):
            continue
        if not view.has_amount and not view.has_balance and not view.date_token and not view.text:
            continue
        # Amount-less transfer attribution (often pasted with statement opening
        # balance) — never a standalone funded operation.
        if not view.has_amount and _is_transfer_attribution_body(view.text or ""):
            continue
        # Thin head already fused with attribution, but Docling never delivered
        # money on either layout row — drop the empty shell.
        flat_cf = (view.text or "").casefold()
        if (
            not view.has_amount
            and "перевод на" in flat_cf
            and "перевод от" in flat_cf
        ):
            continue
        kept.append(list(row))
    return kept if kept else [list(r) for r in matrix]


def assess_operation_row_quality(
    row_columns: Dict[str, str],
    *,
    column_roles: Optional[Sequence[str]] = None,
) -> Tuple[float, List[str]]:
    """
    Score one logical operation for product quality gates.

    Returns (score 0..1, warning codes). Not bank-specific — uses roles/values.
    """
    warnings: List[str] = []
    cols = {str(k): str(v) for k, v in (row_columns or {}).items() if v is not None}
    if not cols:
        return 0.0, ["empty_row"]

    roles = [str(r) for r in (column_roles or [])]
    texts: List[str] = []
    amounts: List[str] = []
    dates: List[str] = []
    for i, (k, v) in enumerate(cols.items()):
        role = roles[i] if i < len(roles) else ""
        hint = _header_role_hint(k)
        effective = role or (hint.value if hint else "")
        if effective in ("category", "description", "other", ""):
            if hint in (ColumnRole.CATEGORY, ColumnRole.DESCRIPTION) or effective in (
                "category",
                "description",
            ):
                texts.append(v)
            elif effective == "other" and not cell_looks_like_amount(v) and not cell_looks_like_date(v):
                texts.append(v)
        if effective == "amount" or hint == ColumnRole.AMOUNT or _AMOUNT_HEADER_RE.search(k):
            amounts.append(v)
        if effective == "date" or hint == ColumnRole.DATE or _DATE_HEADER_RE.search(k):
            dates.append(v)

    # Fallback scan when roles missing / misaligned.
    if not texts:
        for k, v in cols.items():
            if _CATEGORY_HEADER_RE.search(k) or _DESCRIPTION_HEADER_RE.search(k):
                texts.append(v)
    if not amounts:
        for k, v in cols.items():
            if _AMOUNT_HEADER_RE.search(k) and not _BALANCE_HEADER_RE.search(k):
                amounts.append(v)
    if not dates:
        for k, v in cols.items():
            if _DATE_HEADER_RE.search(k):
                dates.append(v)

    text = normalize_text_cell(" ".join(texts))
    amount_ok = any(cell_looks_like_amount(a) for a in amounts)
    date_ok = any(bool(_first_date_token(d)) for d in dates)

    if not date_ok:
        warnings.append("missing_date")
    if not amount_ok:
        warnings.append("missing_amount")
    if not text:
        warnings.append("missing_description")
    elif _is_thin_operation_head(text):
        warnings.append("thin_description")
    elif _is_desc_truncated(text) and len(text) < 40:
        warnings.append("truncated_description")
    if text.count("Операция по") >= 2 or (
        _CARD_OP_COMPLETE_RE.search(text)
        and _GLUED_NEXT_OP_RE.search(" " + text)
        and _split_glued_operation_text(text)
    ):
        warnings.append("packed_dual_operation")

    score = 1.0 - 0.22 * len(warnings)
    return max(0.0, min(1.0, score)), warnings


def assess_schema_quality(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
) -> Tuple[float, List[str]]:
    warnings: List[str] = []
    if not columns:
        return 0.0, ["empty_schema"]
    bases = [_base_header_name(c).casefold() for c in columns]
    if len(bases) != len(set(bases)):
        warnings.append("duplicate_header_bases")
    if len(columns) > 12:
        warnings.append("very_wide_schema")
    if matrix:
        profiles = [
            _profile_column([row[i] if i < len(row) else "" for row in matrix])
            for i in range(len(columns))
        ]
        if not any(p.date_ratio >= 0.2 or p.amount_ratio >= 0.2 for p in profiles):
            warnings.append("no_date_or_amount_signal")
    score = 1.0 - 0.15 * len(warnings)
    return max(0.0, min(1.0, score)), warnings


def extract_ordered_cells(
    values: Sequence[str],
    value_indices: Sequence[int],
) -> List[str]:
    """Pick raw row cells in schema order (skipping dropped noise columns)."""
    if not value_indices:
        return [str(v) for v in values]
    return [
        str(values[idx]) if idx < len(values) else ""
        for idx in value_indices
    ]


def repair_parsed_table(
    parsed: ParsedPipeTable,
    *,
    locked_columns: Optional[Sequence[str]] = None,
    locked_roles: Optional[Sequence[ColumnRole]] = None,
) -> ParsedPipeTable:
    """
    Post-parse repair pipeline (layout → logical operations):

      1. project cells / merge phantom columns (or force locked file schema)
      2. drop repeated page-header echoes
      3. realign shifted columns by role
      4. unglue packed dual-ops onto following tails
      5. explode remaining dual-ops inside one cell
      6. stitch OPEN/META/TAIL continuation rows
      7. normalize cell values by role
      8. quality-gate residual orphan tails
    """
    matrix = [extract_ordered_cells(row, parsed.value_indices) for row in parsed.data_rows]
    columns = list(parsed.columns)
    columns, matrix = merge_phantom_columns(columns, matrix)

    if locked_columns:
        # File-level schema is authoritative after the first table.
        schema = list(locked_columns)
        if len(columns) == len(schema):
            columns = schema
            matrix = [
                (list(row) + [""] * max(0, len(schema) - len(row)))[: len(schema)]
                for row in matrix
            ]
        else:
            remapped: List[List[str]] = []
            for row in matrix:
                local_map = {
                    columns[i]: (row[i] if i < len(row) else "")
                    for i in range(len(columns))
                }
                projected = remap_row_columns_to_canonical(local_map, schema)
                remapped.append([projected.get(c, "") for c in schema])
            matrix = remapped
            columns = schema
        roles = (
            list(locked_roles)
            if locked_roles and len(locked_roles) == len(columns)
            else infer_column_roles(columns, matrix)
        )
        matrix = drop_repeated_header_rows(matrix, columns)
    else:
        roles = infer_column_roles(columns, matrix)

    matrix = realign_shifted_rows(columns, matrix, roles)
    matrix = unglue_packed_rows(columns, matrix, roles)
    matrix = explode_packed_operations(columns, matrix, roles)
    roles = infer_column_roles(columns, matrix) if not locked_columns else roles
    matrix = stitch_continuation_rows(columns, matrix, roles)
    if not locked_columns:
        roles = infer_column_roles(columns, matrix)
    matrix = normalize_matrix_cells(columns, matrix, roles)
    matrix = drop_orphan_fragment_rows(columns, matrix, roles)
    score, warnings = assess_schema_quality(columns, matrix)
    if locked_columns:
        warnings = list(warnings) + ["schema_locked"]
        score = max(score, 0.85)
    if warnings:
        logger.info(
            "[table_schema_normalize] schema quality=%.2f warnings=%s columns=%s",
            score,
            warnings,
            columns,
        )
    return ParsedPipeTable(
        columns=columns,
        data_rows=matrix,
        raw_header_cells=list(parsed.raw_header_cells),
        value_indices=list(range(len(columns))),
        quality_score=score,
        quality_warnings=tuple(warnings),
        column_roles=tuple(r.value for r in roles),
    )


def parse_markdown_pipe_table_schema(
    md: str,
    *,
    locked_columns: Optional[Sequence[str]] = None,
    locked_roles: Optional[Sequence[str]] = None,
) -> Optional[ParsedPipeTable]:
    """
    Parse a markdown pipe table with multi-line / multi-row header support,
    then repair Docling artifacts into a stable visual schema.

    When ``locked_columns`` is set (page 2+ of the same statement), local headers
    are only used to find the table body — canonical schema is not rebuilt.
    """
    lines = [ln for ln in (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines):
        return None

    sep_idx: Optional[int] = None
    for k in range(i, len(lines)):
        if _is_separator_line(lines[k]):
            sep_idx = k
            break
    if sep_idx is None:
        return None

    header_rows: List[List[str]] = []
    for k in range(i, sep_idx):
        if not lines[k].strip():
            continue
        if not _is_pipe_line(lines[k]):
            continue
        header_rows.append(_split_pipe_row(lines[k]))
    if not header_rows:
        return None

    raw_header_cells = _merge_header_rows(header_rows)
    columns, value_indices = normalize_header_schema(raw_header_cells)
    if not columns:
        return None

    data_rows: List[List[str]] = []
    for k in range(sep_idx + 1, len(lines)):
        if not lines[k].strip():
            continue
        if not _is_pipe_line(lines[k]):
            continue
        cells = _split_pipe_row(lines[k])
        if not any(clean_cell_text(c) for c in cells):
            continue
        data_rows.append(cells)

    # Subtitle row mistakenly placed after separator — only learn it on page 1.
    if not locked_columns and data_rows and looks_like_subtitle_row(data_rows[0]):
        raw_header_cells = _merge_header_rows([list(r) for r in header_rows] + [data_rows[0]])
        columns, value_indices = normalize_header_schema(raw_header_cells)
        data_rows = data_rows[1:]
    elif locked_columns and data_rows and (
        looks_like_subtitle_row(data_rows[0])
        or looks_like_repeated_header_row(data_rows[0], locked_columns)
    ):
        data_rows = data_rows[1:]

    if not columns:
        return None

    role_enums: Optional[List[ColumnRole]] = None
    if locked_roles:
        try:
            role_enums = [ColumnRole(r) for r in locked_roles]
        except ValueError:
            role_enums = None

    parsed = ParsedPipeTable(
        columns=columns,
        data_rows=data_rows,
        raw_header_cells=raw_header_cells,
        value_indices=value_indices,
    )
    return repair_parsed_table(
        parsed,
        locked_columns=locked_columns,
        locked_roles=role_enums,
    )


def parsed_pipe_table_from_geometry(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    locked_columns: Optional[Sequence[str]] = None,
    locked_roles: Optional[Sequence[str]] = None,
    source: str = "docling_grid",
) -> Optional[ParsedPipeTable]:
    """
    Build a repaired ParsedPipeTable from a native Docling/geometry matrix.

    Skips markdown serialization — preferred path for bank statements.
    """
    raw_headers = [str(h or "") for h in headers]
    columns, value_indices = normalize_header_schema(raw_headers)
    if not columns:
        return None

    data_rows: List[List[str]] = []
    for row in rows:
        cells = [str(c or "") for c in row]
        if not any(clean_cell_text(c) for c in cells):
            continue
        data_rows.append(cells)

    if not locked_columns and data_rows and looks_like_subtitle_row(data_rows[0]):
        raw_headers = [
            _join_cell_parts(raw_headers[i] if i < len(raw_headers) else "", data_rows[0][i] if i < len(data_rows[0]) else "")
            for i in range(max(len(raw_headers), len(data_rows[0])))
        ]
        # Prefer merge via header rows helper when shapes match; else primary labels.
        columns, value_indices = normalize_header_schema(raw_headers)
        data_rows = data_rows[1:]
    elif locked_columns and data_rows and (
        looks_like_subtitle_row(data_rows[0])
        or looks_like_repeated_header_row(data_rows[0], locked_columns)
    ):
        data_rows = data_rows[1:]

    if not columns:
        return None

    role_enums: Optional[List[ColumnRole]] = None
    if locked_roles:
        try:
            role_enums = [ColumnRole(r) for r in locked_roles]
        except ValueError:
            role_enums = None

    parsed = ParsedPipeTable(
        columns=columns,
        data_rows=data_rows,
        raw_header_cells=list(raw_headers),
        value_indices=value_indices,
        quality_warnings=(f"source:{source}",),
    )
    repaired = repair_parsed_table(
        parsed,
        locked_columns=locked_columns,
        locked_roles=role_enums,
    )
    if repaired is None:
        return None
    warnings = tuple(
        w for w in (repaired.quality_warnings or ()) if not str(w).startswith("source:")
    ) + (f"source:{source}",)
    return ParsedPipeTable(
        columns=repaired.columns,
        data_rows=repaired.data_rows,
        raw_header_cells=repaired.raw_header_cells,
        value_indices=repaired.value_indices,
        quality_score=repaired.quality_score,
        quality_warnings=warnings,
        column_roles=repaired.column_roles,
    )


def align_values_to_schema(
    values: Sequence[str],
    schema: Sequence[str],
) -> Dict[str, str]:
    """Map already-ordered cells onto schema by position; pad/truncate safely."""
    out: Dict[str, str] = {}
    for i, name in enumerate(schema):
        raw = values[i] if i < len(values) else ""
        cell = clean_cell_text(raw)
        cell = re.sub(r"\s*\n\s*", " ", cell).strip()
        if cell:
            out[name] = cell
    return out


def remap_row_columns_to_canonical(
    row_columns: Dict[str, str],
    canonical: Sequence[str],
) -> Dict[str, str]:
    """Remap a row's keys onto a locked file-level schema."""
    if not row_columns:
        return {}
    keys = list(row_columns.keys())
    values = [str(row_columns[k]) for k in keys]

    if len(keys) == len(canonical):
        return {canonical[i]: values[i] for i in range(len(canonical)) if values[i]}

    local_norm = [primary_header_label(k) or k for k in keys]
    used_local: set[int] = set()
    out: Dict[str, str] = {}
    for canon in canonical:
        best_i, best_score = -1, 0.0
        for i, loc in enumerate(local_norm):
            if i in used_local:
                continue
            score = _name_similarity(canon, loc)
            if score > best_score:
                best_score, best_i = score, i
        if best_i >= 0 and best_score >= 0.55:
            used_local.add(best_i)
            val = values[best_i].strip()
            if val:
                out[canon] = re.sub(r"\s*\n\s*", " ", clean_cell_text(val)).strip()
    return out


def normalize_stored_row_columns(row_columns: Dict[str, str]) -> Dict[str, str]:
    """Rewrite stored keys to primary labels and normalize cell values."""
    out: Dict[str, str] = {}
    for key, value in (row_columns or {}).items():
        if value is None:
            continue
        primary = primary_header_label(str(key)) or str(key).strip()
        if not primary or is_noise_header_label(primary):
            continue
        role = _header_role_hint(primary) or ColumnRole.OTHER
        text = normalize_cell_by_role(str(value), role)
        existing = out.get(primary)
        if existing is None or (text.strip() and not str(existing).strip()):
            out[primary] = text
    return out


def lookup_column_value(row_columns: Dict[str, str], header: str) -> str:
    """Resolve a display header against possibly-noisy stored keys."""
    if not row_columns or not header:
        return ""
    if header in row_columns:
        return str(row_columns[header] or "")

    target = (primary_header_label(header) or header).casefold()
    best_val = ""
    best_score = 0.0
    for key, value in row_columns.items():
        primary = primary_header_label(str(key)) or str(key)
        if primary.casefold() == target or str(key).casefold() == target:
            return str(value or "")
        score = _name_similarity(primary, header)
        if score > best_score:
            best_score = score
            best_val = str(value or "")
    return best_val if best_score >= 0.7 else ""


def project_row_columns_to_headers(
    row_columns: Dict[str, str],
    headers: Sequence[str],
) -> Dict[str, str]:
    """Align a row's cells onto a coalesced header list for UI/export."""
    out: Dict[str, str] = {}
    for header in headers:
        value = lookup_column_value(row_columns, header)
        if value:
            out[header] = value
    return out


def coalesce_header_union(headers: Sequence[str]) -> List[str]:
    """Collapse a noisy union of headers (already ingested rows) into primaries."""
    primaries: List[str] = []
    for h in headers:
        primary = primary_header_label(h)
        if primary and not is_noise_header_label(primary):
            primaries.append(primary)

    unique: List[str] = []
    for label in primaries:
        fold = label.casefold()
        if any(u.casefold() == fold for u in unique):
            continue
        if any(
            fold.startswith(u.casefold()) and fold != u.casefold() and len(u) >= 4
            for u in unique
        ):
            continue
        unique = [
            u
            for u in unique
            if not (
                u.casefold().startswith(fold)
                and u.casefold() != fold
                and len(fold) >= 4
            )
        ]
        unique.append(label)
    return unique


def lock_or_align_schema(
    *,
    local_columns: Sequence[str],
    canonical: Optional[Sequence[str]],
) -> Tuple[List[str], bool]:
    """
    Returns (schema_to_use, established_new_canonical).

    First table establishes canonical. Later page tables keep that schema —
    repeated headers are not re-learned. Adopt local only when the segment
    looks like a genuinely different register (weak name overlap).
    """
    local = list(local_columns)
    if not local:
        return list(canonical or []), False
    if not canonical:
        return local, True
    if len(local) == len(canonical):
        return list(canonical), False
    hits = 0
    for loc in local:
        if any(_name_similarity(loc, c) >= 0.7 for c in canonical):
            hits += 1
    # Strong preference for locked file schema on subsequent pages.
    if hits >= 1 or abs(len(local) - len(canonical)) <= 1:
        return list(canonical), False
    reverse_hits = sum(
        1
        for c in canonical
        if any(_name_similarity(c, loc) >= 0.7 for loc in local)
    )
    if reverse_hits >= 1:
        return list(canonical), False
    return local, True
