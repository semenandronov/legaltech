"""Тесты LLM-планировщика legal corpus (mock + merge)."""
from __future__ import annotations

from app.services.chat.legal_query_plan import build_legal_retrieval_plan
from app.services.chat.legal_retrieval_planner import (
    LegalCorpusRetrievalPlanLLM,
    _merge_plans,
    _planner_system_prompt,
    plan_legal_corpus_retrieval_llm,
    resolve_legal_retrieval_plan,
)


def test_planner_prompt_covers_full_bankruptcy_not_only_61():
    text = _planner_system_prompt(max_queries=6, legal_research=True)
    assert "general_bankruptcy" in text
    assert "по умолчанию" in text.lower() or "не подставляй" in text.lower()
    assert "61.2" not in text or "не подставляй" in text.lower()


def test_merge_plans_llm_queries_first():
    det = build_legal_retrieval_plan(
        "оспаривание сделки",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    llm = LegalCorpusRetrievalPlanLLM(
        topic="limitation_challenge",
        instrument_ids=["fz-127", "plenum-63"],
        required_articles=["61.2", "61.9"],
        search_queries=["статья 61.9 127-ФЗ исковая давность оспаривание"],
        rationale="LLM test",
        user_intent_summary="Срок оспаривания",
    )
    merged, source = _merge_plans("за какой период ФУ оспаривает сделки", det, llm)
    assert source == "llm+deterministic"
    assert "61.2" in merged.required_articles
    assert "61.9" in merged.required_articles
    assert merged.search_queries[0].startswith("статья 61.9")
    assert "plenum-63" in merged.instrument_ids


def test_resolve_plan_fallback_when_llm_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.legal_retrieval_planner._llm_planner_enabled",
        lambda: False,
    )
    plan, source = resolve_legal_retrieval_plan(
        "статья 61 и 62",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    assert source == "deterministic"
    assert "61" in plan.required_articles
    assert "62" in plan.required_articles


def test_plan_llm_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.services.chat.legal_retrieval_planner._llm_planner_enabled",
        lambda: False,
    )
    assert plan_legal_corpus_retrieval_llm("тест") is None
