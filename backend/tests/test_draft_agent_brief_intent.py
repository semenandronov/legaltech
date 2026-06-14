"""Tests for draft brief intent parsing and routing."""
from __future__ import annotations

from app.services.draft_agent.brief_intent import parse_draft_brief


def test_parse_financial_statement_of_claim_with_parties():
    prompt = (
        "Подготовь иск о взыскании долга и неустойки по поставке оборудования. "
        "Истец — Вектор-М, ответчик — ТехноСфера."
    )
    intent = parse_draft_brief(prompt)
    assert intent.document_type_hint == "исковое заявление"
    assert intent.requires_financial_calc is True
    assert intent.requires_materials_pipeline is True
    assert intent.routing_reason == "financial_statement_of_claim"
    assert "истец" in intent.parties_from_brief
    assert "ответчик" in intent.parties_from_brief
    assert "Вектор" in intent.parties_from_brief["истец"]
    assert "ТехноСфера" in intent.parties_from_brief["ответчик"]


def test_effective_mode_keeps_catalog_fill_for_financial_claim():
    intent = parse_draft_brief(
        "Подготовь иск о взыскании долга и неустойки. Истец — Альфа, ответчик — Бета."
    )
    assert intent.effective_template_mode("catalog_fill") == "catalog_fill"
    assert intent.effective_template_mode("template_guide") == "template_guide"


def test_simple_form_stays_catalog_fill():
    intent = parse_draft_brief("Заполни поля справки о задолженности")
    assert intent.requires_materials_pipeline is False
    assert intent.effective_template_mode("catalog_fill") == "catalog_fill"
