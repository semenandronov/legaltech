"""Tests for case/global legal intent classification."""
from __future__ import annotations

from app.services.chat.legal_intent import (
    apply_norm_only_case_budget,
    case_rag_should_run,
    classify_case_legal_intent,
    has_case_material_markers,
    is_general_reference_law_question,
    is_pure_norm_lookup_query,
    legal_corpus_graded_sufficient,
)
from app.services.chat.global_langgraph_service import _route_by_rules
from app.services.chat.tier_graph_nodes import grade_retrieval_node, sync_execution_tier_node


def test_classify_norm_only_article_127_fz():
    intent, reason = classify_case_legal_intent(
        "о чем статья 61 в 127 фз",
        legal_research=True,
        mode="garant",
        enable_garant=True,
    )
    assert intent == "norm_only"
    assert "legal_norm" in reason or "norm" in reason


def test_classify_norm_and_case_with_delo_marker():
    intent, _ = classify_case_legal_intent(
        "что говорит ст. 61 127-фз про наш договор в деле",
        legal_research=True,
        mode="garant",
    )
    assert intent == "norm_and_case"


def test_apply_norm_only_budget_skips_case_rag():
    bp = apply_norm_only_case_budget({"execution_tier": "mixed", "recall_k": 100})
    assert bp["recall_k"] == 0
    assert bp["rerank_enabled"] is False
    assert bp.get("case_rag_skipped") is True


def test_case_rag_should_not_run_for_norm_only():
    state = {"legal_intent": "norm_only", "budget_profile": {"case_rag_skipped": True}}
    assert case_rag_should_run(state) is False


def test_grade_retrieval_ok_when_legal_corpus_sufficient():
    state = {
        "execution_tier": "mixed",
        "question": "ст. 61 127-фз",
        "rag_documents": [],
        "garant_context": "x" * 600,
        "legal_route": {"meta": {"sufficient": True, "used_fast_path": True, "doc_count": 5}},
    }
    out = grade_retrieval_node(state)
    assert out.get("grade_retrieval_ok") is True


def test_sync_execution_tier_sets_norm_only_intent():
    out = sync_execution_tier_node(
        {
            "question": "о чем статья 61 в 127 фз",
            "mode": "garant",
            "enable_garant": True,
            "legal_research": True,
            "budget_profile": {"execution_tier": "mixed", "recall_k": 100},
        }
    )
    assert out.get("legal_intent") == "norm_only"
    bp = out.get("budget_profile") or {}
    assert bp.get("recall_k") == 0


def test_global_route_pure_norm_to_law():
    route = _route_by_rules(
        "о чем статья 61 в 127 фз",
        has_matter=True,
        legal_enabled=True,
    )
    assert route == "law"


def test_is_pure_norm_lookup():
    assert is_pure_norm_lookup_query("статья 61 127-фз") is True
    assert has_case_material_markers("найди в договоре пункт 3") is True
    assert is_pure_norm_lookup_query("найди в договоре пункт 3") is False


def test_legal_corpus_graded_sufficient_fast_path():
    assert legal_corpus_graded_sufficient(
        {
            "garant_context": "a" * 400,
            "legal_route": {"meta": {"used_fast_path": True, "articles_missing": []}},
        }
    )


def test_legal_corpus_graded_insufficient_when_articles_missing():
    assert not legal_corpus_graded_sufficient(
        {
            "garant_context": "a" * 400,
            "legal_route": {
                "meta": {
                    "sufficient": True,
                    "topic": "article_lookup",
                    "articles_missing": ["62"],
                }
            },
        }
    )


def test_classify_norm_only_fu_challenge_period():
    q = "За какой период финансовый управляющий имеет право оспаривать сделки должника?"
    assert is_general_reference_law_question(q) is True
    intent, reason = classify_case_legal_intent(
        q,
        legal_research=True,
        mode="garant",
        enable_garant=True,
    )
    assert intent == "norm_only"
    assert "legal_norm" in reason or "norm" in reason
