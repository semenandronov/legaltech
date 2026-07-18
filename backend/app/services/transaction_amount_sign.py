"""
Signed amount convention for bank-statement rows.

Single source of truth for how debit/credit become a signed ``amount_rub``:

    amount_rub > 0  → credit / inflow  (поступление)
    amount_rub < 0  → debit  / outflow (списание)

Russian debit-card statements (Сбер and similar) typically put:
    - an explicit ``+`` on credits: ``+2 000,00``
    - no sign on spends: ``305,00``

Separate Debit/Credit columns store magnitudes; we apply the sign from the column.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional, Tuple

RawSign = Literal["plus", "minus", "none"]
FlowDirection = Literal["debit", "credit"]

_ZERO = Decimal("0")


def detect_explicit_sign(raw: Optional[str]) -> RawSign:
    """Detect a leading + / − in the cell text (ignoring currency and spaces)."""
    text = (raw or "").strip().replace("\u2212", "-").replace("\u00a0", " ")
    if not text:
        return "none"
    # Skip currency/labels until we hit a digit or an explicit sign before a digit.
    for i, ch in enumerate(text):
        if ch in "+-" and i + 1 < len(text) and (text[i + 1].isdigit() or text[i + 1] in " \t"):
            # "+ 2 000" / "-3100" / "+2 000,00"
            # Avoid treating a lone trailing dash as a sign.
            rest = text[i + 1 :].lstrip()
            if rest and rest[0].isdigit():
                return "plus" if ch == "+" else "minus"
        if ch.isdigit():
            return "none"
    return "none"


def normalize_signed_amount(
    parsed: Optional[Decimal],
    *,
    raw: str = "",
    flow: Optional[str] = None,
) -> Tuple[Optional[Decimal], Optional[str]]:
    """
    Normalize a parsed magnitude into signed amount_rub + flow_direction.

    Priority:
      1) explicit flow from Debit/Credit columns
      2) explicit + / − in the amount cell
      3) unsigned magnitude → debit (card-statement convention)
    """
    if parsed is None:
        return None, flow
    if parsed == _ZERO:
        return _ZERO, flow

    magnitude = abs(parsed)
    flow_norm = (flow or "").strip().lower()
    if flow_norm == "debit":
        return -magnitude, "debit"
    if flow_norm == "credit":
        return magnitude, "credit"

    sign = detect_explicit_sign(raw)
    if sign == "plus":
        return magnitude, "credit"
    # Explicit minus OR no sign → debit.
    return -magnitude, "debit"


def effective_amount_rub(
    amount_rub: Optional[Decimal],
    *,
    amount_raw: Optional[str] = None,
    flow_direction: Optional[str] = None,
) -> Optional[Decimal]:
    """
    Signed amount for analytics / filters.

    Prefer already-correct ``amount_rub``. If legacy rows were stored as unsigned
    positives, recover the sign from ``flow_direction`` / ``amount_raw``.

    Card-statement convention (unsigned cell → debit) is applied only when
    ``amount_raw`` is present — otherwise we trust the stored signed value.
    """
    if amount_rub is None:
        return None

    flow = (flow_direction or "").strip().lower()
    if flow == "debit":
        return -abs(amount_rub)
    if flow == "credit":
        return abs(amount_rub)

    # Already signed correctly (new ingest or explicit minus in DB).
    if amount_rub < _ZERO:
        return amount_rub

    if amount_rub == _ZERO:
        return _ZERO

    raw = (amount_raw or "").strip()
    if not raw:
        # No cell text — trust the stored signed amount (fixtures / post-ingest).
        return amount_rub

    signed, _ = normalize_signed_amount(amount_rub, raw=raw, flow=None)
    return signed