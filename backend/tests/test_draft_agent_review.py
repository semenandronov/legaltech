"""Tests for draft agent review helper."""
from __future__ import annotations

from app.services.draft_agent.review import review_draft_html


def test_review_accepts_valid_html():
    html = (
        "<section><h2>Исковое заявление</h2>"
        "<p>Истец просит взыскать с ответчика задолженность в размере 1 000 000 рублей "
        "по договору поставки от 01.06.2024.</p></section>"
    )
    out = review_draft_html(html)
    assert out["passed"] is True
    assert out["gap_count"] == 0


def test_review_flags_unbalanced_html():
    html = "<section><p>Текст документа без закрытия секции, недостаточно для полноценного черновика.</p>"
    out = review_draft_html(html)
    assert out["passed"] is False
    assert "html_structure_unbalanced" in out["issues"]


def test_review_warns_on_gap_markers():
    html = (
        "<section><h2>Иск</h2><p>Истец: ООО «Альфа». "
        "ИНН истца: [ИНН истца]. Сумма иска: 500 000 руб.</p></section>"
    )
    out = review_draft_html(html)
    assert out["passed"] is True
    assert out["gap_count"] == 1
    assert any("gap:" in w for w in out["warnings"])


def test_review_flags_financial_claim_without_penalty_amount():
    html = (
        "<section><h2>Исковое заявление</h2>"
        "<h3>Просительная часть</h3>"
        "<p>Прошу взыскать с ответчика задолженность 3 000 000 руб. и неустойку руб.</p>"
        "</section>"
    )
    out = review_draft_html(
        html,
        financial_claim=True,
        verified_penalty="150 000 руб.",
        verified_total="3 150 000 руб.",
    )
    assert out["passed"] is False
    assert "penalty_amount_missing" in out["issues"]


def test_review_flags_empty_prayer_after_proshu_sud():
    html = (
        "<section><h2>Просительная часть</h2><p>Прошу суд:</p></section>"
        "<section><h2>Цена иска</h2><p>4 083 000 руб.</p></section>"
    )
    out = review_draft_html(html, financial_claim=True)
    assert out["passed"] is False
    assert "prayer_section_unfilled" in out["issues"]
