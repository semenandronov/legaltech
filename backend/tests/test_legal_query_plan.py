"""Тесты детерминированного плана legal retrieval."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.chat.legal_query_plan import (
    LegalRetrievalPlan,
    build_hybrid_queries_from_plan,
    build_legal_retrieval_plan,
    extract_all_article_numbers,
    is_near_duplicate_of_question,
    is_repeal_only_snippet,
    plan_coverage,
    plan_is_sufficient,
    sanitize_planner_search_query,
)


def test_extract_all_articles_61_and_62():
    arts = extract_all_article_numbers("о чем статья 61 и 62 из 127 фз")
    assert "61" in arts
    assert "62" in arts


def test_plan_challenge_transactions_topic_no_hardcoded_articles():
    plan = build_legal_retrieval_plan(
        "За какой период финансовый управляющий имеет право оспаривать сделки должника?",
        instrument_ids=["fz-127", "plenum-63"],
    )
    assert plan.topic in ("challenge_transactions", "limitation_challenge")
    assert "61.2" not in plan.required_articles
    assert "61.1" not in plan.required_articles


def test_plan_article_lookup_two_articles():
    plan = build_legal_retrieval_plan(
        "о чем статья 61 и 62 из 127 фз",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    assert plan.topic == "article_lookup"
    assert "61" in plan.user_articles
    assert "62" in plan.user_articles


def test_repeal_only_snippet():
    assert is_repeal_only_snippet("Статья 23 утратила силу с 01.01.2020")
    assert not is_repeal_only_snippet("Статья 61.\n1. Определения суда..." + "x" * 600)


def test_plan_sufficient_challenge_core_by_volume():
    plan = LegalRetrievalPlan(
        topic="challenge_transactions",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(
            page_content="Статья 61.2. Подозрительные сделки. " + "норма " * 80,
            metadata={"section_title": "Статья 61.2", "article_number": "61.2"},
        ),
        Document(
            page_content="Статья 61.1. Основания оспаривания. " + "текст " * 60,
            metadata={"section_title": "Статья 61.1", "article_number": "61.1"},
        ),
    ]
    assert plan_is_sufficient(docs, plan)


def test_plan_sufficient_volume_without_user_articles():
    """Без явных статей — достаточность по объёму контекста."""
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(
            page_content="Статья 223.2. Условия внесудебного банкротства. " + "текст " * 150,
            metadata={"section_title": "Статья 223.2", "article_number": "223.2"},
        ),
    ]
    assert plan_is_sufficient(docs, plan)


def test_plan_sufficient_user_articles_both_needed():
    plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["14.1", "223.1"],
        user_articles=["14.1", "223.1"],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(
            page_content="Статья 223.1. Общие положения. " + "текст " * 100,
            metadata={"section_title": "Статья 223.1"},
        ),
    ]
    assert not plan_is_sufficient(docs, plan)


def test_plan_coverage_missing_62():
    plan = build_legal_retrieval_plan(
        "статья 61 и 62",
        instrument_ids=["fz-127"],
        legal_research=True,
    )
    docs = [
        Document(
            page_content="Статья 61. Порядок обжалования " + "x" * 300,
            metadata={"article_number": "61"},
        ),
    ]
    cov = plan_coverage(docs, plan)
    assert "61" in cov["covered"]
    assert "62" in cov["missing"]


def test_sanitize_drops_hallucinated_article_number():
    allowed = frozenset()
    assert sanitize_planner_search_query("статья 7 закон о банкротстве порог", allowed) is None
    assert sanitize_planner_search_query(
        "минимальный размер требований возбуждение банкротства", allowed
    )


def test_sanitize_keeps_user_article_in_query():
    allowed = frozenset({"61", "62"})
    assert sanitize_planner_search_query("статья 61 127-ФЗ", allowed) == "статья 61 127-ФЗ"


def test_build_hybrid_queries_includes_facts_as_separate_passes():
    q = "Какой порог для банкротства юрлица и период просрочки?"
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=[
            "минимальный размер требований возбуждение банкротства юридическое лицо",
            "статья 7 закон о банкротстве",
        ],
        rationale="test",
        facts=[
            "минимальный период просрочки исполнения обязательств",
            "минимальный размер совокупных требований к юрлицу",
        ],
    )
    queries = build_hybrid_queries_from_plan(plan, q)
    joined = " | ".join(queries).lower()
    assert "статья 7" not in joined
    assert any("просроч" in x for x in queries)
    assert any("размер" in x or "требован" in x for x in queries)
    assert not any(is_near_duplicate_of_question(x, q) for x in queries)


def test_infer_comparative_bankruptcy_coverage_targets():
    q = (
        "В чем ключевое отличие признаков банкротства гражданина от признаков банкротства "
        "юридического лица при подаче заявления кредитором?"
    )
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=["признаки банкротства"],
        rationale="test",
        facts=["субъекты: гражданин, юридическое лицо", "порог для юрлица: 2 млн"],
    )
    from app.services.chat.legal_query_plan import coverage_target_articles

    targets = coverage_target_articles(plan, q)
    assert "33" in targets
    assert "213.3" in targets
    assert "3" in targets


def test_plan_coverage_flags_missing_inferred_article():
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
        facts=["гражданин", "юридическое лицо", "кредитор"],
    )
    q = "отличие банкротства гражданина и юридического лица кредитором"
    docs = [
        Document(page_content="x" * 300, metadata={"article_number": "213.3"}),
    ]
    cov = plan_coverage(docs, plan, question=q)
    assert "213.3" in cov["covered"]
    assert "33" in cov["missing"]


def test_build_hybrid_queries_prioritizes_threshold_facts():
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=[],
        instrument_ids=["fz-127"],
        search_queries=[f"search query {i}" for i in range(5)],
        rationale="test",
        facts=[
            "субъекты: гражданин, юридическое лицо",
            "порог для гражданина: не менее 500 тысяч рублей",
            "порог для юрлица: не менее 2 миллионов рублей",
        ],
    )
    queries = build_hybrid_queries_from_plan(plan, "сравнение гражданина и юрлица")
    assert any("500" in x or "пятьсот" in x.lower() or "пятисот" in x.lower() for x in queries)
    assert any("миллион" in x.lower() for x in queries)
