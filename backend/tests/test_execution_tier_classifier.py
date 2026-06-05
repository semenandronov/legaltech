"""Tier LLM classifier gating."""
from unittest.mock import MagicMock, patch

from app.services.chat.tier_classifier import (
    ExecutionTierClassification,
    classify_execution_tier_llm,
    tier_llm_classifier_enabled,
)


def test_classifier_disabled_by_default():
    assert tier_llm_classifier_enabled() is False
    assert classify_execution_tier_llm(question="какая сумма") is None


def test_classifier_returns_tier_when_enabled(monkeypatch):
    monkeypatch.setenv("CASE_ASSISTANT_TIER_LLM_ENABLED", "true")
    monkeypatch.setenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true")
    from app.config import config

    config.CASE_ASSISTANT_TIER_LLM_ENABLED = True
    config.CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED = True

    mock_result = ExecutionTierClassification(
        execution_tier="instant",
        confidence=0.9,
        reason="narrow fact",
    )
    mock_llm = MagicMock()
    mock_structured = MagicMock()
    mock_structured.invoke.return_value = mock_result
    mock_llm.with_structured_output.return_value = mock_structured

    with patch("app.services.llm_factory.create_llm", return_value=mock_llm):
        tier = classify_execution_tier_llm(question="какая сумма по п. 3")
    assert tier == "instant"
