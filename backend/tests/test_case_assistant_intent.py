"""Case assistant intent layer — systemic routing, not per-query patches."""
from app.services.chat.case_assistant_intent import resolve_case_assistant_intent
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.execution_tier import infer_execution_tier_heuristic


def test_corpus_overview_without_attached_files():
    intent = resolve_case_assistant_intent(
        question="о чем документы",
        attached_files_count=0,
        corpus_size=4,
    )
    assert intent.primary == "case_corpus_overview"
    assert intent.task_type == "multi_doc_synthesis"
    assert intent.response_shape == "executive_summary"


def test_corpus_overview_standard_tier_summary_path(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True

    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "multi_doc_synthesis",
        corpus_size=4,
        question="о чем документы",
        attached_files_count=0,
    )
    assert profile["execution_tier"] == "standard"
    assert profile["retrieval_path"] == "summary_overview"
    assert profile["rerank_enabled"] is False


def test_drill_down_routes_to_legal_reasoning_memorandum():
    intent = resolve_case_assistant_intent(
        question="подробнее про возражение шар",
        corpus_size=4,
    )
    assert intent.primary == "drill_down"
    assert intent.task_type == "legal_reasoning"
    assert intent.depth_tier == "fast"
    assert intent.response_shape == "memorandum"


def test_drill_down_execution_tier_is_standard_not_instant():
    intent = resolve_case_assistant_intent(question="подробнее про возражение")
    tier, reason = infer_execution_tier_heuristic(
        question="подробнее про возражение",
        task_type=intent.task_type,
        depth_tier=intent.depth_tier,
        primary_intent=intent.primary,
    )
    assert tier == "standard"
    assert reason == "intent_drill_down"


def test_narrow_fact_stays_instant_tier():
    intent = resolve_case_assistant_intent(question="какая сумма в п. 6.2")
    tier, _ = infer_execution_tier_heuristic(
        question="какая сумма в п. 6.2",
        task_type=intent.task_type,
        depth_tier=intent.depth_tier,
        primary_intent=intent.primary,
    )
    assert intent.primary == "narrow_fact"
    assert tier == "instant"


def test_infer_task_and_depth_delegates_to_intent():
    task_type, depth, clarify, reason, conf = ConversationPolicyService.infer_task_and_depth(
        question="о чем документы",
        corpus_size=3,
        attached_files_count=0,
    )
    assert task_type == "multi_doc_synthesis"
    assert depth == "fast"
    assert not clarify
    assert reason == "case_corpus_overview"
    assert conf >= 0.85


def test_budget_profile_includes_primary_intent():
    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "legal_reasoning",
        corpus_size=4,
        question="подробнее про возражение",
        attached_files_count=0,
    )
    assert profile.get("primary_intent") == "drill_down"
    assert profile.get("response_shape") == "memorandum"
    assert profile.get("execution_tier") == "standard"
    assert profile.get("rerank_tier") == "light"
    assert profile.get("max_tokens") == 1500
