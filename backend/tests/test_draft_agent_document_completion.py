"""Tests for second-pass document completion planning."""
from __future__ import annotations

from app.services.draft_agent.document_completion import (
    build_document_completion_plan,
    build_completion_gap_report,
)
from app.services.draft_pipeline.schemas import ExtractedFacts, FinancialSummary, VerifiedCalculations


def _verified_facts() -> ExtractedFacts:
    verified = VerifiedCalculations(
        principal_outstanding="3 000 000 руб.",
        penalty_amount="1 083 000 руб.",
        total_claim="4 083 000 руб.",
        state_duty="28 615 руб.",
        penalty_days=361,
    )
    return ExtractedFacts(
        document_type="исковое заявление",
        financial=FinancialSummary(verified=verified),
    )


def test_completion_plan_triggers_for_empty_prayer():
    html = (
        "<section><h2>Просительная часть</h2><p>Прошу суд:</p></section>"
        "<section><h2>Цена иска</h2><p>4 083 000 руб.</p></section>"
    )
    plan = build_document_completion_plan(
        html,
        facts=_verified_facts(),
        financial_claim=True,
    )
    assert plan.run_completion is True
    assert any("просительн" in g for g in plan.gap_labels)


def test_completion_plan_includes_state_duty_gap():
    html = (
        "<section><h2>Цена иска</h2><p>4 083 000 руб. (госпошлина: [сумма] руб.)</p></section>"
        "<section><h2>Просительная часть</h2>"
        "<p>Прошу суд:</p><ol><li>Взыскать 3 000 000 руб. долга и 1 083 000 руб. неустойки.</li></ol>"
        "</section>"
    )
    plan = build_document_completion_plan(
        html,
        facts=_verified_facts(),
        financial_claim=True,
    )
    assert plan.run_completion is True
    assert any("госпошлин" in g for g in plan.gap_labels)


def test_completion_gap_report_lists_items():
    plan = build_document_completion_plan(
        "<p>Прошу суд:</p>",
        facts=_verified_facts(),
        financial_claim=True,
    )
    report = build_completion_gap_report(plan)
    assert "Исправь только" in report or "Проверь документ" in report
