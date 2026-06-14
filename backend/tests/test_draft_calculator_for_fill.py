"""Тесты калькулятора в catalog_fill."""
from unittest.mock import patch

from app.services.draft_calculator_for_fill import (
    _catalog_has_amount_fields,
    _digits_only_money,
    attach_calculator_context_for_fill,
)
from app.services.draft_pipeline.schemas import ExtractedFacts, FinancialSummary, VerifiedCalculations
from app.services.draft_template_schemas import TemplateFieldSpec


def test_catalog_has_amount_fields():
    specs = [
        TemplateFieldSpec(field_id="v1", marker="{{ court_name }}", variable="court_name"),
    ]
    assert not _catalog_has_amount_fields(specs)
    specs.append(
        TemplateFieldSpec(field_id="v2", marker="{{ debt_total }}", variable="debt_total"),
    )
    assert _catalog_has_amount_fields(specs)


def test_digits_only_money():
    assert _digits_only_money("2 500 000 руб.") == "2500000"


@patch("app.services.draft_calculator_for_fill.run_verify_financials")
@patch("app.services.draft_calculator_for_fill.extract_case_fact_passport")
def test_attach_calculator_context_applied(mock_passport, mock_verify):
    facts = ExtractedFacts(
        financial=FinancialSummary(
            verified=VerifiedCalculations(
                principal_outstanding="2 300 000",
                penalty_amount="200 000",
                total_claim="2 500 000",
                state_duty="50 000",
                penalty_start_date="2025-01-15",
                penalty_end_date="2026-06-01",
            )
        )
    )
    mock_passport.return_value = facts
    mock_verify.return_value = facts

    specs = [
        TemplateFieldSpec(field_id="v1", marker="{{ debt_total }}", variable="debt_total"),
    ]
    out, meta = attach_calculator_context_for_fill(
        user_context="Составь заявление кредитора, долг 2.3 млн",
        rag_context="Договор: неустойка 0.1% в день",
        field_specs=specs,
    )
    assert meta["calculator_applied"] is True
    assert "КАЛЬКУЛЯТОР" in out
    assert "debt_total: 2500000" in out
    assert "debt_main: 2300000" in out
    assert meta["calculator_variables"]["debt_total"] == "2500000"


def test_attach_skips_without_amount_fields():
    specs = [
        TemplateFieldSpec(field_id="v1", marker="{{ court_name }}", variable="court_name"),
    ]
    out, meta = attach_calculator_context_for_fill(
        user_context="запрос",
        rag_context="контекст",
        field_specs=specs,
    )
    assert out == "запрос"
    assert meta["calculator_attempted"] is False
