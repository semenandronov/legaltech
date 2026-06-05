"""Тесты детерминированного плана legal retrieval."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.chat.legal_query_plan import (
    LegalRetrievalPlan,
    build_legal_retrieval_plan,
    extract_all_article_numbers,
    is_repeal_only_snippet,
    plan_coverage,
    plan_is_sufficient,
)


def test_extract_all_articles_61_and_62():
    arts = extract_all_article_numbers("о чем статья 61 и 62 из 127 фз")
    assert "61" in arts
    assert "62" in arts


def test_plan_challenge_transactions_topic():
    plan = build_legal_retrieval_plan(
        "За какой период финансовый управляющий имеет право оспаривать сделки должника?",
        instrument_ids=["fz-127", "plenum-63"],
    )
    assert plan.topic in ("challenge_transactions", "limitation_challenge")
    assert "61.2" in plan.required_articles
    assert "61.1" in plan.required_articles


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


def test_plan_sufficient_challenge_core():
    plan = build_legal_retrieval_plan(
        "может ли финансовый управляющий оспаривать сделки должника",
        instrument_ids=["fz-127"],
    )
    docs = [
        Document(
            page_content="Статья 61.2. Подозрительные сделки. " + "норма " * 80,
            metadata={"section_title": "Статья 61.2"},
        ),
        Document(
            page_content="Статья 61.1. Основания оспаривания. " + "текст " * 60,
            metadata={"section_title": "Статья 61.1"},
        ),
    ]
    assert plan_is_sufficient(docs, plan)


def test_plan_sufficient_plan_driven_not_61_2_core():
    """Sufficiency по required_articles плана, не по жёсткому ядру 61.2."""
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=["223.2"],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(
            page_content="Статья 223.2. Условия внесудебного банкротства. " + "текст " * 120,
            metadata={"section_title": "Статья 223.2"},
        ),
    ]
    assert plan_is_sufficient(docs, plan)


def test_plan_sufficient_two_required_both_needed():
    plan = LegalRetrievalPlan(
        topic="general_bankruptcy",
        required_articles=["14.1", "223.1"],
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
            metadata={},
        ),
    ]
    cov = plan_coverage(docs, plan)
    assert "61" in cov["covered"] or "61" not in plan.required_articles
    assert "62" in cov["missing"]
