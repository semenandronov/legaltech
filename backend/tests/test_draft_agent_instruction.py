"""Tests for instruction helpers."""
from __future__ import annotations

from app.services.draft_agent.brief_intent import parse_draft_brief
from app.services.draft_agent.instruction import apply_brief_to_facts, build_document_instruction
from app.services.draft_pipeline.schemas import ExtractedFacts


def test_apply_brief_seeds_parties():
    intent = parse_draft_brief("Иск. Истец — Вектор-М, ответчик — ТехноСфера.")
    facts = ExtractedFacts(document_type="", parties={})
    merged = apply_brief_to_facts(facts, intent)
    assert "Вектор" in merged.parties.get("истец", "")
    assert "ТехноСфера" in merged.parties.get("ответчик", "")


def test_build_document_instruction_includes_financial_notes():
    intent = parse_draft_brief("Подготовь иск о взыскании долга и неустойки.")
    text = build_document_instruction(
        user_question="Подготовь иск",
        facts=ExtractedFacts(),
        brief_intent=intent,
    )
    assert "Просительная часть" in text
    assert "верифицированного расчёта" in text
