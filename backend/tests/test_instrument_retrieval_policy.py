"""Instrument-only turns: tier + grade_retrieval + case RAG skip."""
from __future__ import annotations

from app.services.chat.execution_tier import infer_execution_tier_heuristic, resolve_execution_tier
from app.services.chat.legal_intent import case_rag_should_run, court_practice_graded_sufficient
from app.services.chat.tier_graph_nodes import grade_retrieval_node


def test_court_practice_tier_standard_not_mixed():
    tier, reason = infer_execution_tier_heuristic(
        question="практика по оспариванию сделок",
        task_type="legal_reasoning",
        depth_tier="deep",
        court_practice=True,
        legal_research=False,
    )
    assert tier == "standard"
    assert reason == "court_practice_toggle"


def test_legal_research_alone_standard_not_mixed():
    tier, reason = infer_execution_tier_heuristic(
        question="срок по ст 61.10 127-ФЗ",
        task_type="legal_reasoning",
        depth_tier="deep",
        legal_research=True,
        court_practice=False,
    )
    assert tier == "standard"
    assert reason == "legal_research_toggle"


def test_case_rag_skipped_for_court_practice_only():
    assert case_rag_should_run(
        {"enable_court_practice": True, "enable_garant": False, "legal_intent": "case_primary"}
    ) is False


def test_grade_retrieval_ok_when_court_practice_context_rich():
    state = {
        "execution_tier": "standard",
        "enable_court_practice": True,
        "court_practice_context": "x" * 500,
        "court_practice_documents": [{"page_content": "a", "metadata": {}}],
        "rag_documents": [],
        "budget_profile": {"max_retrieval_rounds": 2},
        "retrieval_round": 0,
    }
    out = grade_retrieval_node(state)
    assert out.get("grade_retrieval_ok") is True


def test_resolve_execution_tier_passes_court_practice():
    tier, _ = resolve_execution_tier(
        question="дела по банкротству",
        task_type="legal_reasoning",
        depth_tier="deep",
        court_practice=True,
        legal_research=False,
    )
    assert tier == "standard"
