"""
Token-boundary matching for bank-statement description filters.

Matches whole alphanumeric tokens (VK in «VK*1234*ADS»), not arbitrary
substrings (VK inside «AVK»). No merchant dictionaries — structural only.

For needles of length >= 4, also allows token prefix match so Russian
inflected forms («Иванов» → «Иванову») and brand stems still work.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy import ColumnElement, String, cast, or_

# Same notion of a "word" as practical statement tokenization:
# letters (Latin + Cyrillic), digits, underscore.
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9_]+", re.UNICODE)
_BOUNDARY_CLASS = r"A-Za-zА-Яа-яЁё0-9_"
# Shorter needles (VK, OK) must be exact tokens — prefix would be too loose.
_PREFIX_MATCH_MIN_LEN = 4


def iter_description_tokens(text: str) -> tuple[str, ...]:
    raw = text or ""
    if not raw:
        return ()
    return tuple(_TOKEN_RE.findall(raw))


def description_token_match(haystack: str, needle: str) -> bool:
    """True if needle equals (or, if long enough, prefixes) a whole token."""
    token = (needle or "").strip()
    if not token:
        return True
    needle_l = token.lower()
    allow_prefix = len(needle_l) >= _PREFIX_MATCH_MIN_LEN
    for part in iter_description_tokens(haystack):
        part_l = part.lower()
        if part_l == needle_l:
            return True
        if allow_prefix and part_l.startswith(needle_l):
            return True
    return False


def any_field_description_token_match(fields: Iterable[str], needle: str) -> bool:
    token = (needle or "").strip()
    if not token:
        return True
    return any(description_token_match(str(part or ""), token) for part in fields)


def postgres_token_boundary_pattern(needle: str) -> str:
    """
    Case-insensitive PostgreSQL regex: whole-token match for needle.

    Uses explicit Unicode letter/digit boundaries (not locale-dependent [[:alnum:]]).
    """
    token = (needle or "").strip()
    if not token:
        return r"(?!)"  # never matches; caller should skip empty needles
    escaped = re.escape(token)
    if len(token) >= _PREFIX_MATCH_MIN_LEN:
        # Token equals needle or starts with it (inflections / brand stems).
        return rf"(^|[^{_BOUNDARY_CLASS}]){escaped}[{_BOUNDARY_CLASS}]*"
    return rf"(^|[^{_BOUNDARY_CLASS}]){escaped}([^{_BOUNDARY_CLASS}]|$)"


def sql_columns_token_match(columns: Iterable[Any], needle: str) -> ColumnElement[bool]:
    """OR of ~* token-boundary predicates across SQL columns."""
    pattern = postgres_token_boundary_pattern(needle)
    parts = []
    for col in columns:
        parts.append(col.op("~*")(pattern))
    if not parts:
        raise ValueError("sql_columns_token_match requires at least one column")
    return or_(*parts)


def sql_transaction_description_token_match(
    *,
    description_col: Any,
    row_columns_col: Any,
    datetime_text_col: Any,
    amount_raw_col: Any,
    needle: str,
) -> ColumnElement[bool]:
    return sql_columns_token_match(
        (
            description_col,
            cast(row_columns_col, String),
            datetime_text_col,
            amount_raw_col,
        ),
        needle,
    )
