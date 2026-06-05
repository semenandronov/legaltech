"""User-facing LLM kwargs — reasoning channel contract."""
from app.services.llm_factory import user_facing_llm_reasoning_kwargs


def test_user_facing_disables_reasoning_for_normal_mode():
    assert user_facing_llm_reasoning_kwargs(mode="normal") == {"reasoning_mode": "disabled"}


def test_user_facing_disables_reasoning_for_garant_and_draft():
    assert user_facing_llm_reasoning_kwargs(mode="garant") == {"reasoning_mode": "disabled"}
    assert user_facing_llm_reasoning_kwargs(mode="draft") == {"reasoning_mode": "disabled"}


def test_user_facing_keeps_reasoning_for_deep_think():
    assert user_facing_llm_reasoning_kwargs(mode="deep_think") == {}
