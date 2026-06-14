"""Tests for draft fact coverage assessment."""
from __future__ import annotations

from app.services.draft_agent.coverage import assess_fact_coverage
from app.services.draft_pipeline.schemas import ExtractedFacts, FinancialLineItem, FinancialSummary, PenaltyTerms


def test_coverage_flags_missing_parties_and_inn():
    facts = ExtractedFacts(document_type="исковое заявление")
    assessment = assess_fact_coverage(
        user_prompt="Составь иск, найди ИНН сторон, пересчитай неустойку",
        facts=facts,
        template_mode="template_guide",
    )
    gap_ids = {g.gap_id for g in assessment.gaps}
    assert not assessment.sufficient
    assert "parties" in gap_ids
    assert "requisites" in gap_ids


def test_coverage_sufficient_with_parties_and_amounts():
    facts = ExtractedFacts(
        document_type="исковое заявление",
        parties={"истец": "ООО Вектор", "ответчик": "ООО Техно"},
        amounts={"основной долг": "4 500 000"},
        identifiers={"ИНН ответчика": "7701234567"},
        penalty_terms=PenaltyTerms(
            payment_term_value=10,
            penalty_rate_percent_per_day="0.1",
            principal_amount="4500000",
        ),
        financial=FinancialSummary(
            principal_claim="4 500 000",
            partial_payments=[
                FinancialLineItem(date="2025-07-10", amount="500 000", source="п/п 1"),
            ],
        ),
    )
    assessment = assess_fact_coverage(
        user_prompt="Иск о взыскании долга и неустойки, учти частичные оплаты",
        facts=facts,
        template_mode="template_guide",
    )
    assert assessment.sufficient
    assert assessment.score >= 0.5


def test_build_chat_summary_lists_gaps():
    from app.services.draft_agent.instruction import build_chat_summary

    text = build_chat_summary(
        document_title="Иск",
        document_id="doc-1",
        case_id="case-1",
        fill_mode="template_guide",
        coverage_gaps=[{"label": "ИНН/реквизиты сторон"}],
    )
    assert "Иск" in text
    assert "ИНН" in text or "реквизит" in text
