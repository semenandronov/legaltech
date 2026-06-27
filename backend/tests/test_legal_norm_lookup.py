"""Тесты structured norm lookup и metadata coverage."""
from __future__ import annotations

from langchain_core.documents import Document

from app.services.chat.legal_query_plan import (
    LegalRetrievalPlan,
    doc_metadata_matches_article,
    plan_coverage,
    plan_is_sufficient,
)
from app.services.legal_norm_lookup import NormLookupRequest, should_prefer_norm_tree


def test_doc_metadata_matches_article_exact():
    d61 = Document(page_content="текст", metadata={"article_number": "61"})
    d619 = Document(page_content="текст", metadata={"article_number": "61.9"})
    assert doc_metadata_matches_article(d61, "61")
    assert not doc_metadata_matches_article(d619, "61")
    assert doc_metadata_matches_article(d619, "61.9")


def test_plan_coverage_uses_metadata_not_text_collision():
    plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["61"],
        user_articles=["61"],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(page_content="x" * 300, metadata={"article_number": "61.9", "clause_ref": "1"}),
        Document(page_content="y" * 250, metadata={"article_number": "61", "clause_ref": "1"}),
        Document(page_content="z" * 250, metadata={"article_number": "61", "clause_ref": "2"}),
    ]
    cov = plan_coverage(docs, plan)
    assert "61" in cov["covered"]
    assert plan_is_sufficient(docs, plan)


def test_plan_coverage_clause_ref():
    plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["61"],
        user_articles=["61"],
        user_clause_ref="3",
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    docs = [
        Document(page_content="a" * 300, metadata={"article_number": "61", "clause_ref": "1"}),
        Document(page_content="b" * 300, metadata={"article_number": "61", "clause_ref": "3"}),
    ]
    cov = plan_coverage(docs, plan)
    assert "61" in cov["covered"]


def test_should_prefer_norm_tree_article_lookup():
    plan = LegalRetrievalPlan(
        topic="article_lookup",
        required_articles=["61"],
        user_articles=["61"],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    assert should_prefer_norm_tree(plan)

    plan2 = LegalRetrievalPlan(
        topic="challenge_transactions",
        required_articles=["61.2"],
        instrument_ids=["fz-127"],
        search_queries=[],
        rationale="test",
    )
    assert not should_prefer_norm_tree(plan2)


def test_norm_lookup_request_frozen():
    req = NormLookupRequest(instrument_id="fz-127", article_number="61", clause_ref="3")
    assert req.clause_ref == "3"
