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
  - continuation rows (multi-line cells exported as two rows) are stitched
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
# Strict money: currency, sign, thousands groups, or explicit decimals — never a
# bare digit glued inside a word ("обработки1").
_AMOUNT_TOKEN_RE = re.compile(
    r"(?:"
    r"[+\-]\s*\d{1,3}(?:[\s\u00a0]\d{3})*(?:[.,]\d{2})?"
    r"|\d{1,3}(?:[\s\u00a0]\d{3})+(?:[.,]\d{2})?"
    r"|\d+[.,]\d{2}"
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
    """True for real money tokens; false for footnote digits inside words."""
    flat = re.sub(r"\s+", " ", clean_cell_text(value).replace("\n", " ")).strip()
    if not flat:
        return False
    if _CURRENCY_RE.search(flat) and re.search(r"\d", flat):
        return True
    return bool(_AMOUNT_TOKEN_RE.search(flat))


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
        if hint == ColumnRole.DATE or profile.date_ratio >= 0.4:
            role = ColumnRole.DATE
        elif hint == ColumnRole.BALANCE or (
            profile.amount_ratio >= 0.3 and "остат" in name.casefold()
        ):
            role = ColumnRole.BALANCE
        elif hint == ColumnRole.AMOUNT or profile.amount_ratio >= 0.35:
            role = ColumnRole.AMOUNT
        elif hint == ColumnRole.CATEGORY:
            role = ColumnRole.CATEGORY
        elif hint == ColumnRole.DESCRIPTION or profile.text_ratio >= 0.45:
            role = ColumnRole.DESCRIPTION
        if role in used and role != ColumnRole.OTHER:
            if role == ColumnRole.AMOUNT and ColumnRole.BALANCE not in used:
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


def _first_date_token(value: str) -> str:
    match = _DATE_TOKEN_RE.search(clean_cell_text(value).replace("\n", " "))
    return match.group(0) if match else ""


def stitch_continuation_rows(
    columns: Sequence[str],
    matrix: Sequence[Sequence[str]],
    roles: Optional[Sequence[ColumnRole]] = None,
) -> List[List[str]]:
    """
    Stitch Docling-split multi-line cells exported as two consecutive rows.

    Conservative: only merge when the next row looks like a continuation
    (same date, no money/balance, descriptive text present).
    """
    if len(matrix) < 2:
        return [list(r) for r in matrix]

    role_list = list(roles) if roles is not None else infer_column_roles(columns, matrix)
    date_idxs = [i for i, r in enumerate(role_list) if r == ColumnRole.DATE]
    money_idxs = [
        i for i, r in enumerate(role_list) if r in (ColumnRole.AMOUNT, ColumnRole.BALANCE)
    ]
    text_idxs = [
        i
        for i, r in enumerate(role_list)
        if r in (ColumnRole.CATEGORY, ColumnRole.DESCRIPTION, ColumnRole.OTHER)
    ]

    def _row_has_money(row: Sequence[str]) -> bool:
        idxs = money_idxs or list(range(len(columns)))
        return any(cell_looks_like_amount(row[i]) for i in idxs if i < len(row))

    def _is_continuation(primary: Sequence[str], nxt: Sequence[str]) -> bool:
        if _row_has_money(nxt):
            return False
        if money_idxs:
            for i in money_idxs:
                if i >= len(nxt):
                    continue
                cell = clean_cell_text(nxt[i]).strip()
                if cell and cell not in {"-", "—", "–"}:
                    return False

        next_has_auth = False
        if date_idxs:
            d0 = _first_date_token(
                primary[date_idxs[0]] if date_idxs[0] < len(primary) else ""
            )
            date_next = clean_cell_text(
                nxt[date_idxs[0]] if date_idxs[0] < len(nxt) else ""
            ).replace("\n", " ")
            d1 = _first_date_token(date_next)
            next_has_auth = any(_AUTH_CODE_RE.match(tok) for tok in date_next.split())
            # Operation date and processing date may differ; allow when next
            # carries an auth code (classic multi-line statement cell split).
            if d0 and d1 and d0 != d1 and not next_has_auth:
                return False

        text_payload = False
        for i in text_idxs or range(len(columns)):
            if i >= len(nxt):
                continue
            cell = clean_cell_text(nxt[i]).strip()
            if len(cell) >= 6 and not cell_looks_like_date(cell) and not _TIME_RE.match(cell):
                text_payload = True
                break
        if not text_payload and not next_has_auth:
            return False
        return text_payload or next_has_auth

    out: List[List[str]] = []
    i = 0
    rows = [[str(c) for c in row] for row in matrix]
    while i < len(rows):
        if i + 1 < len(rows) and _is_continuation(rows[i], rows[i + 1]):
            merged = []
            for col_i in range(len(columns)):
                a = rows[i][col_i] if col_i < len(rows[i]) else ""
                b = rows[i + 1][col_i] if col_i < len(rows[i + 1]) else ""
                if col_i in money_idxs:
                    merged.append(a if clean_cell_text(a).strip() else b)
                else:
                    merged.append(_join_cell_parts(a, b))
            out.append(merged)
            i += 2
            continue
        out.append(list(rows[i]))
        i += 1
    return out


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


def repair_parsed_table(parsed: ParsedPipeTable) -> ParsedPipeTable:
    """
    Post-parse repair: project cells, merge phantom columns, stitch continuations.
    """
    matrix = [extract_ordered_cells(row, parsed.value_indices) for row in parsed.data_rows]
    columns = list(parsed.columns)
    columns, matrix = merge_phantom_columns(columns, matrix)
    roles = infer_column_roles(columns, matrix)
    matrix = stitch_continuation_rows(columns, matrix, roles)
    roles = infer_column_roles(columns, matrix)
    score, warnings = assess_schema_quality(columns, matrix)
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


def parse_markdown_pipe_table_schema(md: str) -> Optional[ParsedPipeTable]:
    """
    Parse a markdown pipe table with multi-line / multi-row header support,
    then repair Docling artifacts into a stable visual schema.
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

    # Subtitle row mistakenly placed after separator.
    if data_rows and looks_like_subtitle_row(data_rows[0]):
        raw_header_cells = _merge_header_rows([list(r) for r in header_rows] + [data_rows[0]])
        columns, value_indices = normalize_header_schema(raw_header_cells)
        data_rows = data_rows[1:]

    if not columns:
        return None

    parsed = ParsedPipeTable(
        columns=columns,
        data_rows=data_rows,
        raw_header_cells=raw_header_cells,
        value_indices=value_indices,
    )
    return repair_parsed_table(parsed)


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
    """Rewrite stored keys to primary labels (API / already-ingested rows)."""
    out: Dict[str, str] = {}
    for key, value in (row_columns or {}).items():
        if value is None:
            continue
        primary = primary_header_label(str(key)) or str(key).strip()
        if not primary or is_noise_header_label(primary):
            continue
        text = str(value)
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

    First table establishes canonical. Later tables keep canonical when arity
    matches or names align; otherwise adopt local (genuinely different table).
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
    if hits >= max(2, int(0.6 * len(canonical))):
        return list(canonical), False
    if len(local) > len(canonical):
        reverse_hits = sum(
            1
            for c in canonical
            if any(_name_similarity(c, loc) >= 0.7 for loc in local)
        )
        if reverse_hits >= max(2, int(0.75 * len(canonical))):
            return list(canonical), False
    return local, True
