"""
Amount direction for statement SQL plans (credits vs debits).

Uses question stems — not description_contains on operation text.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Optional, Tuple

AmountSemantics = Literal["any", "credit", "debit", "net"]

_DEBIT_STEM_RE = re.compile(
    r"\b(?:списан|расход|уменьшен|дебет|снят|оплат)\w*",
    re.IGNORECASE,
)
_CREDIT_STEM_RE = re.compile(
    r"\b(?:поступлен|приход|зачислен|кредит|пополн|внесен|входящ)\w*",
    re.IGNORECASE,
)

_DIRECTION_DESC_STOPWORDS = frozenset(
    {
        "поступлений",
        "поступления",
        "поступление",
        "поступлением",
        "списаний",
        "списания",
        "списание",
        "списанием",
        "дебет",
        "дебета",
        "кредит",
        "кредита",
        "приход",
        "прихода",
        "расход",
        "расхода",
    }
)


def infer_amount_semantics(question: str) -> AmountSemantics:
    q = (question or "").strip()
    if not q:
        return "any"
    has_debit = bool(_DEBIT_STEM_RE.search(q))
    has_credit = bool(_CREDIT_STEM_RE.search(q))
    if has_debit and not has_credit:
        return "debit"
    if has_credit and not has_debit:
        return "credit"
    return "any"


def is_direction_description_noise(description_contains: str) -> bool:
    needle = (description_contains or "").strip().lower()
    if not needle:
        return False
    if needle in _DIRECTION_DESC_STOPWORDS:
        return True
    return any(needle.startswith(w) or w.startswith(needle) for w in _DIRECTION_DESC_STOPWORDS)


def amount_filter_bounds(semantics: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    sem = (semantics or "any").strip().lower()
    if sem == "credit":
        return Decimal("0.01"), None
    if sem == "debit":
        return None, Decimal("-0.01")
    return None, None


def amount_semantics_label(semantics: str) -> str:
    sem = (semantics or "any").strip().lower()
    if sem == "credit":
        return "только поступления (сумма > 0)"
    if sem == "debit":
        return "только списания (сумма < 0)"
    if sem == "net":
        return "алгебраическая сумма (поступления и списания)"
    return ""
