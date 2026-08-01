"""
Value-level grounding for tabular evidence gate (OCR-tolerant).

When verbatim quotes fail substring match (spaces, line breaks), structured answers
(INN, sums, case numbers) can still be accepted if their digit/normalized core appears
in the document or retrieval corpus.
"""
from __future__ import annotations

import re
from typing import Optional

from app.services.tabular_extraction_policy import is_na_cell_value
from app.services.tabular_quote_then_answer import normalize_for_grounding

_INN_LEN = frozenset({10, 12})
_CASE_PREFIX_RE = re.compile(r"^[aа]\d{2}-", re.IGNORECASE)


def _normalize_case_number(value: str) -> str:
    t = normalize_for_grounding(value).replace(" ", "")
    t = t.replace("а", "a")
    t = re.sub(r"[-–—]", "-", t)
    return t


def _case_number_in_corpus(value: str, corpus: str) -> bool:
    case_norm = _normalize_case_number(value)
    if len(case_norm) < 8:
        return False
    if not _CASE_PREFIX_RE.match(case_norm):
        return False
    corpus_norm = _normalize_case_number(corpus)
    return case_norm in corpus_norm.replace(" ", "")


def _cell_digits(value: str) -> str:
    return re.sub(r"\D", "", (value or "").replace(",", ".").replace(" ", ""))


def _normalize_contract_ref(value: str) -> str:
    t = normalize_for_grounding(value)
    t = t.replace(" ", "")
    t = re.sub(r"[-–—]", "/", t)
    while "//" in t:
        t = t.replace("//", "/")
    return t


def _corpus_digits(corpus: str) -> str:
    return re.sub(r"\D", "", corpus or "")


def _amount_integer_core(value: str) -> Optional[str]:
    raw = (value or "").strip()
    if not raw or is_na_cell_value(raw):
        return None
    digits = _cell_digits(raw)
    if not digits:
        return None
    if "." in raw.replace(",", "."):
        return digits.split(".")[0] or None
    if len(digits) >= 4:
        return digits
    return None


def value_grounded_in_corpus(
    cell_value: str,
    *,
    column_type: Optional[str] = None,
    corpus: str,
) -> bool:
    """True when a structured cell value is supported by corpus text (not paraphrase)."""
    value = (cell_value or "").strip()
    if not value or is_na_cell_value(value):
        return False
    if not (corpus or "").strip():
        return False

    ctype = (column_type or "text").lower()
    body_norm = normalize_for_grounding(corpus)
    body_compact = body_norm.replace(" ", "")

    if ctype in {"currency", "number", "amount"}:
        core = _amount_integer_core(value)
        if core and len(core) >= 3 and core in _corpus_digits(corpus):
            return True

    digits = _cell_digits(value)
    if digits and len(digits) in _INN_LEN and digits in _corpus_digits(corpus):
        return True

    if digits and len(digits) >= 15 and digits in _corpus_digits(corpus):
        return True

    if _case_number_in_corpus(value, corpus):
        return True

    cref = _normalize_contract_ref(value)
    if "/" in cref and len(cref) >= 6:
        if cref in body_compact or cref.replace("/", "-") in body_compact:
            return True

    if ctype in {"verbatim", "text"} and len(digits) in _INN_LEN and digits in _corpus_digits(corpus):
        return True

    return False


def value_grounded_in_document(
    cell_value: str,
    *,
    column_type: Optional[str] = None,
    original_text: str,
) -> bool:
    return value_grounded_in_corpus(
        cell_value,
        column_type=column_type,
        corpus=original_text or "",
    )
