"""Budget profile recall/final_k tied to execution tier."""
import os

from app.services.chat.conversation_policy_service import ConversationPolicyService
from app.services.chat.execution_tier import adaptive_tier_enabled


def test_fast_fact_lookup_instant_recall_when_adaptive_enabled(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    monkeypatch.setenv("CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS", "3500")
    monkeypatch.setenv("CASE_ASSISTANT_INSTANT_MAX_TOKENS", "300")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    config.CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS = 3500
    config.CASE_ASSISTANT_INSTANT_MAX_TOKENS = 300
    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "fact_lookup",
        corpus_size=40,
        question="какая сумма в п. 6.2",
    )
    assert adaptive_tier_enabled()
    assert profile["execution_tier"] == "instant"
    assert profile["recall_k"] == 16
    assert profile["final_k"] == 6
    assert profile["rerank_enabled"] is True
    assert profile["rerank_tier"] == "light"
    assert profile["max_context_chars"] == 3500
    assert profile["max_tokens"] == 300
    assert profile["tier_contract"]["llm_max_tokens"] == 300


def test_adaptive_disabled_uses_legacy_recall_100(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "false")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = False
    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast", "fact_lookup", corpus_size=40, question="сумма"
    )
    assert profile["recall_k"] == 100
    assert profile["final_k"] > 0


def test_deep_synthesis_recall_100_when_adaptive(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    profile = ConversationPolicyService.budget_profile_for_depth(
        "deep",
        "multi_doc_synthesis",
        corpus_size=40,
        question="сравни условия по всем договорам",
    )
    assert profile["execution_tier"] == "deep"
    assert profile["recall_k"] == 100
    assert profile["rerank_enabled"] is True


def test_greeting_no_retrieval(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    from app.config import config

    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True
    profile = ConversationPolicyService.budget_profile_for_depth(
        "fast",
        "fact_lookup",
        question="Привет!",
    )
    assert profile["execution_tier"] == "no_retrieval"
    assert profile["recall_k"] == 0
