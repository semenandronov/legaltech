"""Tier execution contract — authoritative generation guardrails."""
from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.execution_tier import llm_max_tokens_from_budget


def test_fast_profile_caps_tokens_not_expands(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    monkeypatch.setenv("CASE_ASSISTANT_INSTANT_MAX_TOKENS", "800")
    monkeypatch.setenv("CASE_ASSISTANT_STANDARD_MAX_TOKENS", "1500")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    config.CASE_ASSISTANT_INSTANT_MAX_TOKENS = 800
    config.CASE_ASSISTANT_STANDARD_MAX_TOKENS = 1500

    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "fact_lookup",
        corpus_size=4,
        question="какая сумма в п. 6.2",
    )
    assert profile["execution_tier"] == "instant"
    assert profile["max_tokens"] == 800
    assert profile["tier_contract"]["llm_max_tokens"] == 800
    assert llm_max_tokens_from_budget(profile) == 800


def test_drill_down_profile_standard_tier_and_memorandum_cap(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    monkeypatch.setenv("CASE_ASSISTANT_STANDARD_MAX_TOKENS", "1500")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    config.CASE_ASSISTANT_STANDARD_MAX_TOKENS = 1500

    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "legal_reasoning",
        corpus_size=4,
        question="подробнее про возражение шар",
    )
    assert profile["primary_intent"] == "drill_down"
    assert profile["execution_tier"] == "standard"
    assert profile["response_shape"] == "memorandum"
    assert profile["max_tokens"] == 1500


def test_deep_synthesis_has_higher_cap(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    monkeypatch.setenv("CASE_ASSISTANT_DEEP_MAX_TOKENS", "4500")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    config.CASE_ASSISTANT_DEEP_MAX_TOKENS = 4500

    profile = ConversationPolicyService.budget_profile_for_depth(
        "deep",
        "multi_doc_synthesis",
        corpus_size=40,
        question="сравни условия по всем договорам",
    )
    assert profile["execution_tier"] == "deep"
    assert profile["response_shape"] == "analysis"
    assert profile["primary_intent"] == "cross_doc_analysis"
    assert profile["max_tokens"] == min(6800, 4500)


def test_guardrail_uses_min_not_max_for_context(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    monkeypatch.setenv("CASE_ASSISTANT_STANDARD_MAX_CONTEXT_CHARS", "48000")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    config.CASE_ASSISTANT_STANDARD_MAX_CONTEXT_CHARS = 48000

    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "single_doc_extraction",
        corpus_size=4,
        question="что в договоре",
    )
    assert profile["execution_tier"] == "instant"
    assert profile["max_context_chars"] == 16000
