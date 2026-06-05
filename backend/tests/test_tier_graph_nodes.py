"""Adaptive tier graph routing helpers."""
from app.services.chat.tier_graph_nodes import (
    grade_retrieval_node,
    parallel_retrieval_should_run,
    route_after_execution_tier,
    route_after_grade_retrieval,
    sync_execution_tier_node,
)


def test_route_no_retrieval_to_generate():
    assert route_after_execution_tier({"execution_tier": "no_retrieval"}) == "generate_response"


def test_route_clarify():
    assert route_after_execution_tier({"execution_tier": "clarify"}) == "clarify_response"


def test_parallel_skips_for_clarify():
    assert parallel_retrieval_should_run({"execution_tier": "clarify", "mode": "normal"}) is False


def test_sync_tier_overrides_on_clarification_needed():
    out = sync_execution_tier_node(
        {
            "budget_profile": {"execution_tier": "standard", "recall_k": 35},
            "clarification_needed": True,
        }
    )
    assert out["execution_tier"] == "clarify"


def test_grade_weak_instant_escalates_at_max_rounds():
    state = {
        "execution_tier": "instant",
        "question": "сумма",
        "rag_documents": [],
        "budget_profile": {
            "execution_tier": "instant",
            "max_retrieval_rounds": 1,
            "recall_k": 16,
        },
        "retrieval_round": 0,
    }
    out = grade_retrieval_node(state)
    assert out.get("escalated_from") == "instant"
    assert out.get("execution_tier") == "standard"
    assert route_after_grade_retrieval(out) == "extract_retrieval_task"


def test_grade_sufficient_goes_to_quality_gate():
    state = {
        "execution_tier": "standard",
        "rag_documents": [
            {"page_content": "a", "metadata": {"score": 0.9}},
            {"page_content": "b", "metadata": {"score": 0.8}},
        ],
        "budget_profile": {"max_retrieval_rounds": 2},
        "retrieval_round": 0,
    }
    out = grade_retrieval_node(state)
    assert out.get("grade_retrieval_ok") is True
    assert route_after_grade_retrieval(out) == "rag_quality_gate"
