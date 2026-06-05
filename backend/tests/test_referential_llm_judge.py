"""LLM judge for Turn Context routing."""
from unittest.mock import patch

import pytest

from app.services.chat.referential_classifier import classify_referential_kind
from app.services.chat.referential_llm_judge import (
    ReferentialJudgeDecision,
    _enforce_kind_invariants,
    classify_referential_kind_judge,
)
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.turn_context_evidence import load_prior_turn_evidence_from_turns
from app.services.chat.turn_context_resolution import resolve_turn_context


def _prior_turn() -> list[SessionMessageTurn]:
    return [
        SessionMessageTurn(message_id="u1", role="user", content="расскажи про возражение ШАК"),
        SessionMessageTurn(
            message_id="a1",
            role="assistant",
            content="Возражения должников ШАК и ШЭР на реализацию имущества.",
            evidence={
                "citations": [
                    {
                        "source_id": "f-obj",
                        "chunk_id": "c-1",
                        "quote": "презумпция добросовестности",
                    }
                ],
                "retrieval_metadata": {"file_ids": ["f-obj"]},
            },
        ),
    ]


def test_enforce_kind_invariants_memory_never_retrieves():
    kind, needs = _enforce_kind_invariants("memory_synthesis", True)
    assert kind == "memory_synthesis"
    assert needs is False


def test_enforce_kind_invariants_none_chat_only_becomes_memory():
    kind, needs = _enforce_kind_invariants("none", False)
    assert kind == "memory_synthesis"
    assert needs is False


def test_llm_judge_long_memory_synthesis_question(llm_judge_enabled):
    """Long recap questions bypass regex length gate when LLM routes."""
    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    long_q = (
        "Расскажи своими словами что мы установили про возражения должников "
        "с акцентом на правовую позицию по каждому доводу и объясни "
        "что важнее для стратегии защиты в арбитражном суде"
    )
    assert classify_referential_kind(long_q, has_prior=True) == "none"

    decision = ReferentialJudgeDecision(
        referential_kind="memory_synthesis",
        needs_document_retrieval=False,
        confidence=0.91,
        rationale="recap prior assistant answer",
    )
    with patch(
        "app.services.chat.referential_llm_judge._invoke_llm_judge",
        return_value=decision,
    ):
        result = classify_referential_kind_judge(
            question=long_q,
            has_prior=True,
            prior_evidence=prior,
            turns=_prior_turn(),
        )
    assert result.referential_kind == "memory_synthesis"
    assert result.needs_document_retrieval is False
    assert result.resolver == "llm"


def test_llm_judge_fallback_to_regex_when_llm_unavailable(llm_judge_enabled):
    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    with patch("app.services.chat.referential_llm_judge._invoke_llm_judge", return_value=None):
        result = classify_referential_kind_judge(
            question="КАКИЕ КЛЮЧЕВЫЕ ВЫВОДЫ?",
            has_prior=True,
            prior_evidence=prior,
            turns=_prior_turn(),
        )
    assert result.referential_kind == "memory_synthesis"
    assert result.resolver == "regex_fallback"


def test_regex_safety_when_llm_uncertain_on_memory_synthesis(llm_judge_enabled):
    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    decision = ReferentialJudgeDecision(
        referential_kind="none",
        needs_document_retrieval=True,
        confidence=0.55,
        rationale="uncertain",
    )
    with patch(
        "app.services.chat.referential_llm_judge._invoke_llm_judge",
        return_value=decision,
    ):
        result = classify_referential_kind_judge(
            question="итог?",
            has_prior=True,
            prior_evidence=prior,
            turns=_prior_turn(),
        )
    assert result.referential_kind == "memory_synthesis"
    assert result.resolver == "regex_safety"


def test_resolve_turn_context_uses_judge_standalone_query(llm_judge_enabled):
    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    decision = ReferentialJudgeDecision(
        referential_kind="scoped_deep_read",
        needs_document_retrieval=True,
        confidence=0.88,
        rationale="deictic sum pointer",
        standalone_query="какая сумма указана в пункте 2 возражений ШАК",
    )

    with patch(
        "app.services.chat.referential_llm_judge._invoke_llm_judge",
        return_value=decision,
    ):
        resolution = resolve_turn_context(
            question="А эта сумма в п. 2?",
            prior_evidence=prior,
            turns=_prior_turn(),
        )

    assert resolution.referential_kind == "scoped_deep_read"
    assert "сумма" in resolution.standalone_query.lower()
    assert resolution.query_resolver == "llm_judge"
    assert resolution.routing_resolver in {"llm", "llm_regex_agree"}


@pytest.fixture
def llm_judge_enabled(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "TURN_CONTEXT_LLM_JUDGE_ENABLED", True)
