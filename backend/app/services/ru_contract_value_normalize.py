"""
Canonical normalization for RU contract identifiers and money amounts.

Used by contract_facts rules and tabular currency cells — one source of truth.
"""
from __future__ import annotations

import re
from typing import Optional

# Contract numbers are latin/digit/punctuation — never Cyrillic prose (e.g. glued «от»).
_CONTRACT_NUMBER_TOKEN_RE = re.compile(
    r"^[0-9A-Za-z][0-9A-Za-z/\-–—\._]*[0-9A-Za-z]$|^[0-9A-Za-z]$"
)
_CYRILLIC_RUN_RE = re.compile(r"[А-Яа-яЁё]+")
_MONEY_SPAN_RE = re.compile(
    r"\d[\d\s\u00a0\u202f.,]*\d|\d+"
)


def normalize_ru_contract_number(raw: str) -> str:
    """
    Normalize a captured contract/DS number.

    Stops before glued Russian words (№ 03/03-2022/1от → 03/03-2022/1).
    """
    text = (raw or "").strip().strip(" .,;:)»\"'")
    if not text:
        return ""
    # Cut at first Cyrillic run (common OCR glue: «1от», «1г»).
    cut = _CYRILLIC_RUN_RE.search(text)
    if cut and cut.start() > 0:
        text = text[: cut.start()]
    elif cut and cut.start() == 0:
        return ""
    text = text.strip(" .,;:)/-–—_")
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"/{2,}", "/", text)
    if not text or not any(ch.isdigit() for ch in text):
        return ""
    if not _CONTRACT_NUMBER_TOKEN_RE.match(text):
        # Keep digit/slash/dash core even if odd chars slipped in.
        core = re.sub(r"[^0-9A-Za-z/\-._]", "", text)
        return core.strip("/-._") or ""
    return text


def normalize_ru_money_amount(raw: str, *, with_rub_suffix: bool = True) -> Optional[str]:
    """
    Collapse OCR/thousand spacing into a canonical RU money display.

    Examples:
      «959 335» / «959 3 35» / «959335 руб.» → «959 335 руб.»
    """
    if raw is None:
        return None
    flat = (
        str(raw)
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("\u2212", "-")
        .strip()
    )
    if not flat:
        return None

    match = _MONEY_SPAN_RE.search(flat)
    if not match:
        return None
    chunk = match.group(0)
    compact = re.sub(r"[\s\u00a0\u202f]", "", chunk).replace(",", ".")
    if compact.count(".") > 1:
        # Keep last decimal separator only.
        head, _, tail = compact.rpartition(".")
        compact = head.replace(".", "") + "." + tail
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", compact):
        digits = re.sub(r"[^\d]", "", compact)
        if not digits:
            return None
        compact = digits
    try:
        value = float(compact)
    except ValueError:
        return None
    if value < 0:
        return None

    int_part = int(value)
    frac_part = int(round((value - int_part) * 100))
    if frac_part == 100:
        int_part += 1
        frac_part = 0

    int_str = f"{int_part:,}".replace(",", " ")
    if frac_part:
        display = f"{int_str},{frac_part:02d}"
    else:
        display = int_str
    if with_rub_suffix:
        return f"{display} руб."
    return display


def money_plain_normalized(raw: str) -> Optional[str]:
    """Plain numeric normalized form for comparisons (no spaces): 959335 or 959335.50."""
    display = normalize_ru_money_amount(raw, with_rub_suffix=False)
    if not display:
        return None
    return display.replace(" ", "").replace(",", ".")
