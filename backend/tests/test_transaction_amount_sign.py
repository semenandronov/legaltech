"""Unit tests for signed amount convention (debit < 0, credit > 0)."""

from decimal import Decimal

from app.services.transaction_amount_sign import (
    detect_explicit_sign,
    effective_amount_rub,
    normalize_signed_amount,
)


def test_detect_explicit_sign():
    assert detect_explicit_sign("+2 000,00") == "plus"
    assert detect_explicit_sign("+ 2 000,00 ₽") == "plus"
    assert detect_explicit_sign("-3 100.00") == "minus"
    assert detect_explicit_sign("\u22123 100.00") == "minus"
    assert detect_explicit_sign("305,00") == "none"
    assert detect_explicit_sign("1 720,00") == "none"
    assert detect_explicit_sign("") == "none"


def test_normalize_card_statement_convention():
    # Sber-style: unsigned = spend, "+" = top-up.
    debit, flow = normalize_signed_amount(Decimal("305"), raw="305,00", flow=None)
    assert debit == Decimal("-305")
    assert flow == "debit"

    credit, flow = normalize_signed_amount(Decimal("2000"), raw="+2 000,00", flow=None)
    assert credit == Decimal("2000")
    assert flow == "credit"

    explicit_debit, flow = normalize_signed_amount(Decimal("3100"), raw="-3 100.00", flow=None)
    assert explicit_debit == Decimal("-3100")
    assert flow == "debit"


def test_normalize_debit_credit_columns():
    debit, flow = normalize_signed_amount(Decimal("5000"), raw="5 000,00", flow="debit")
    assert debit == Decimal("-5000") and flow == "debit"

    credit, flow = normalize_signed_amount(Decimal("5000"), raw="5 000,00", flow="credit")
    assert credit == Decimal("5000") and flow == "credit"


def test_effective_amount_recovers_legacy_unsigned_rows():
    # Legacy ingest stored spends as positive with unsigned amount_raw.
    assert effective_amount_rub(
        Decimal("1720.00"), amount_raw="1 720,00", flow_direction=None
    ) == Decimal("-1720.00")
    assert effective_amount_rub(
        Decimal("2000"), amount_raw="+2 000,00", flow_direction=None
    ) == Decimal("2000")
    # Already correctly signed.
    assert effective_amount_rub(
        Decimal("-305"), amount_raw="305,00", flow_direction=None
    ) == Decimal("-305")
    # flow_direction wins.
    assert effective_amount_rub(
        Decimal("100"), amount_raw="100", flow_direction="debit"
    ) == Decimal("-100")
    # No amount_raw → trust stored sign (do not flip positives).
    assert effective_amount_rub(Decimal("500"), amount_raw=None, flow_direction=None) == Decimal(
        "500"
    )
