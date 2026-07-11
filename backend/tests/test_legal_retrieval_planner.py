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


def test_planner_prompt_covers_facts_not_article_guessing():
    text = _planner_system_prompt(max_queries=6, legal_research=True)
    assert "general_bankruptcy" in text
    assert "facts" in text
    assert "не угадывай" in text.lower() or "не указывай номера статей" in text.lower()
    assert "запрещено" in text.lower()
    assert "конкурсный кредитор" in text.lower()
    assert "127-фз" in text.lower() or "127‑фз" in text.lower()


def test_merge_plans_llm_queries_without_llm_articles():
    det = build_legal_retrieval_plan(
        "оспаривание сделки",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    llm = LegalCorpusRetrievalPlanLLM(
        topic="limitation_challenge",
        instrument_ids=["fz-127", "plenum-63"],
        facts=["срок оспаривания сделок финансовым управляющим", "127-ФЗ"],
        search_queries=["исковая давность оспаривание сделки финансовым управляющим 127-ФЗ"],
        rationale="LLM test",
        user_intent_summary="Срок оспаривания",
    )
    merged, source = _merge_plans("за какой период ФУ оспаривает сделки", det, llm)
    assert source == "llm+deterministic"
    assert "61.2" not in merged.required_articles
    assert "61.9" not in merged.required_articles
    assert merged.search_queries[0].startswith("исковая")
    assert "plenum-63" in merged.instrument_ids
    assert len(merged.facts) >= 1


def test_merge_plans_keeps_user_articles_from_question():
    det = build_legal_retrieval_plan(
        "статья 61 и 62",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    llm = LegalCorpusRetrievalPlanLLM(
        topic="article_lookup",
        instrument_ids=["fz-127"],
        facts=["содержание статей"],
        search_queries=["статья 61 127-ФЗ", "статья 62 127-ФЗ"],
        rationale="test",
    )
    merged, _ = _merge_plans("статья 61 и 62", det, llm)
    assert "61" in merged.required_articles
    assert "62" in merged.required_articles


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


def test_parse_planner_json_payload_facts():
    from app.services.chat.legal_retrieval_planner import _parse_planner_json_payload

    raw = (
        '{"topic":"general_bankruptcy","instrument_ids":["fz-127"],'
        '"facts":["порог возбуждения банкротства юрлица","период просрочки"],'
        '"search_queries":["минимальный размер требований банкротство юридическое лицо"],'
        '"rationale":"test","user_intent_summary":"пороги"}'
    )
    plan = _parse_planner_json_payload(raw)
    assert plan is not None
    assert plan.topic == "general_bankruptcy"
    assert "fz-127" in plan.instrument_ids
    assert len(plan.facts) >= 1
    assert plan.search_queries


def test_parse_planner_legacy_required_articles_becomes_facts():
    from app.services.chat.legal_retrieval_planner import _parse_planner_json_payload

    raw = (
        '{"topic":"general_bankruptcy","instrument_ids":["fz-127"],'
        '"required_articles":["3","6.1"],"search_queries":["статья 3 127-ФЗ"],'
        '"rationale":"test"}'
    )
    plan = _parse_planner_json_payload(raw)
    assert plan is not None
    assert plan.facts
    assert not hasattr(plan, "required_articles") or getattr(plan, "required_articles", None) in (None, [])


def test_merge_strips_hallucinated_article_in_search_queries():
    det = build_legal_retrieval_plan(
        "Какой минимальный размер требований для банкротства юрлица и период просрочки?",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    llm = LegalCorpusRetrievalPlanLLM(
        topic="general",
        instrument_ids=["fz-127"],
        facts=[
            "минимальный размер совокупных требований юридическое лицо",
            "минимальный период просрочки возбуждение дела",
        ],
        search_queries=[
            "минимальный размер требований возбуждение банкротства юридическое лицо",
            "период просрочки возбуждение дела о банкротстве",
            "статья 7 закон о банкротстве порог задолженности",
            "актуальные изменения порог банкротства 2024 2025",
        ],
        rationale="test",
    )
    merged, _ = _merge_plans(
        "Какой минимальный размер требований для банкротства юрлица и период просрочки?",
        det,
        llm,
    )
    joined = " | ".join(merged.search_queries).lower()
    assert "статья 7" not in joined
    assert merged.topic == "general_bankruptcy"
    assert len(merged.facts) >= 2


def test_merge_skips_full_question_from_router_when_llm_has_enough_queries():
    q = (
        "Какой минимальный размер совокупных требований установлен для возбуждения дела о банкротстве "
        "юридического лица и каков минимальный период просрочки?"
    )
    det = build_legal_retrieval_plan(q, instrument_ids=[], legal_research=True)
    assert any(q.lower() == sq.lower() for sq in det.search_queries)
    llm = LegalCorpusRetrievalPlanLLM(
        topic="general_bankruptcy",
        instrument_ids=["fz-127"],
        facts=["порог суммы", "период просрочки"],
        search_queries=[
            "минимальный размер требований возбуждение банкротства юридическое лицо",
            "период просрочки возбуждение дела о банкротстве",
            "актуальные изменения порог банкротства",
        ],
        rationale="test",
    )
    merged, _ = _merge_plans(q, det, llm)
    assert not any(sq.lower() == q.lower() for sq in merged.search_queries)
