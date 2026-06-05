"""Tests for pipeline recall_k cap with micro-only funnel."""
from __future__ import annotations

from app.services.chat.case_context_pipeline import recall_k_for_budget


def test_recall_k_capped_for_micro_pipeline(monkeypatch):
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_RECALL_K", 100)
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_MICRO_RECALL_K", 40)
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_MICRO_ONLY_RECALL_ENABLED", True)
    monkeypatch.setattr(
        "app.services.chat.case_context_pipeline.pipeline_enabled",
        lambda: True,
    )
    k = recall_k_for_budget({"recall_k": 100})
    assert k == 40


def test_recall_k_respects_small_tier(monkeypatch):
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_MICRO_RECALL_K", 40)
    monkeypatch.setattr("app.config.config.CASE_ASSISTANT_MICRO_ONLY_RECALL_ENABLED", True)
    monkeypatch.setattr(
        "app.services.chat.case_context_pipeline.pipeline_enabled",
        lambda: True,
    )
    k = recall_k_for_budget({"recall_k": 16})
    assert k == 16
