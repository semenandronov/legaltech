"""Tests for deterministic RF financial calculator in draft pipeline."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.draft_pipeline.financial_calculator import (
    apply_verified_financials,
    compute_verified_financials,
    format_money_rub,
    parse_date,
    parse_money,
)
from app.services.draft_pipeline.rf_business_calendar import (
    add_business_days,
    count_penalty_days,
    payment_deadline_and_penalty_start,
)
from app.services.draft_pipeline.schemas import (
    ExtractedFacts,
    FinancialLineItem,
    FinancialSummary,
    PenaltyTerms,
)


def test_parse_date_formats():
    assert parse_date("2025-06-02") == date(2025, 6, 2)
    assert parse_date("02.06.2025") == date(2025, 6, 2)
    assert parse_date("02 июня 2025 года") == date(2025, 6, 2)


def test_parse_money_rub():
    assert parse_money("4 500 000 руб.") == Decimal("4500000")
    assert parse_money("1 500 000") == Decimal("1500000")


def test_ten_business_days_after_act_june_2025():
    """Act 02.06.2025 (Mon) + 10 business days → deadline 17.06, penalty from 18.06."""
    act = date(2025, 6, 2)
    deadline, penalty_start = payment_deadline_and_penalty_start(
        act, 10, term_count_starts="next_day"
    )
    assert deadline == date(2025, 6, 17)
    assert penalty_start == date(2025, 6, 18)


def test_add_business_days_skips_russia_day_holiday():
    # 10 business days from Mon 02.06.2025 must cross 12.06 holiday
    result = add_business_days(date(2025, 6, 2), 10, term_count_starts="next_day")
    assert result == date(2025, 6, 17)


def test_penalty_days_inclusive():
    assert count_penalty_days(date(2025, 6, 18), date(2026, 6, 7)) == 355


def test_full_supply_contract_scenario():
    facts = ExtractedFacts(
        document_type="исковое заявление",
        parties={"истец": "ООО Вектор-М", "ответчик": "ООО ТехноСфера"},
        amounts={"сумма договора": "4 500 000 руб."},
        dates={"дата акта": "2025-06-02"},
        financial=FinancialSummary(
            partial_payments=[
                FinancialLineItem(
                    date="25.06.2025",
                    amount="1 500 000",
                    source="п/п №112",
                )
            ],
        ),
        penalty_terms=PenaltyTerms(
            payment_term_value=10,
            payment_term_unit="business_days",
            payment_term_from="act_signed",
            term_count_starts="next_day",
            act_date="2025-06-02",
            penalty_rate_percent_per_day="0.1",
            principal_amount="4500000",
            penalty_end_date="2026-06-07",
            partial_payments=[
                FinancialLineItem(date="25.06.2025", amount="1 500 000", source="п/п №112")
            ],
        ),
    )

    verified = compute_verified_financials(facts)
    assert verified is not None
    assert verified.payment_deadline == "2025-06-17"
    assert verified.penalty_start_date == "2025-06-18"
    assert verified.penalty_days == 355
    assert parse_money(verified.principal_outstanding) == Decimal("3000000")
    assert parse_money(verified.penalty_amount) == Decimal("1065000")
    assert parse_money(verified.total_claim) == Decimal("4065000")

    updated = apply_verified_financials(facts)
    assert updated.financial.verified is not None
    assert updated.financial.confidence == "high"
    assert "17.06.2025" in updated.financial.computation_method


def test_apply_skipped_without_terms():
    facts = ExtractedFacts(document_type="ходатайство")
    assert apply_verified_financials(facts).financial.verified is None


def test_format_money_rub():
    assert format_money_rub(Decimal("1065000")) == "1 065 000 руб."
