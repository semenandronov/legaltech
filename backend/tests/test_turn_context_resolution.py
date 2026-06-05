"""Turn Context Contract — structural follow-up routing."""
import pytest

from app.services.chat.evidence_plan import apply_turn_context_overrides
from app.services.chat.evidence_scope import resolve_evidence_scope
from app.services.chat.retrieval_router import CaseFileCatalogEntry
from app.services.chat.session_context_resolver import resolve_turn_from_intent_authority
from app.services.chat.session_context_retrieval import is_memory_only_turn, session_context_meta_from_package
from app.services.chat.session_context_types import (
    SessionContextPackage,
    SessionMessageTurn,
    SessionResolveResult,
    TurnRelation,
)
from app.services.chat.turn_context_evidence import load_prior_turn_evidence_from_turns
from app.services.chat.turn_context_resolution import (
    load_and_resolve_turn_context,
    resolve_turn_context,
    session_result_from_turn_context,
)


@pytest.fixture(autouse=True)
def _disable_live_llm_judge(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "TURN_CONTEXT_LLM_JUDGE_ENABLED", False)


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


def test_memory_synthesis_classifies_key_conclusions():
    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    resolution = resolve_turn_context(
        question="КАКИЕ КЛЮЧЕВЫЕ ВЫВОДЫ?",
        prior_evidence=prior,
    )
    assert resolution.referential_kind == "memory_synthesis"
    assert resolution.needs_document_retrieval is False
    assert resolution.suggested_intent == "clarify_prior"
    assert resolution.inherited_file_ids == ("f-obj",)


def test_session_result_from_memory_synthesis():
    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    resolution = resolve_turn_context(
        question="итог?",
        prior_evidence=prior,
    )
    result = session_result_from_turn_context(resolution, prior_evidence=prior)
    assert result.turn_relation is TurnRelation.CLARIFY_PRIOR
    assert result.needs_document_retrieval is False
    assert result.rationale == "turn_context_memory_synthesis"


def test_intent_authority_yields_to_turn_context():
    turns = _prior_turn()
    tc = {"referential_kind": "memory_synthesis", "needs_document_retrieval": False}
    result = resolve_turn_from_intent_authority(
        primary_intent="drill_down",
        intent_confidence=0.9,
        question="КАКИЕ КЛЮЧЕВЫЕ ВЫВОДЫ?",
        turns=turns,
        search_hits=[],
        turn_context=tc,
    )
    assert result is None


def test_apply_turn_context_overrides_memory_synthesis():
    profile = {
        "execution_tier": "standard",
        "recall_k": 35,
        "rerank_enabled": True,
        "primary_intent": "drill_down",
    }
    out = apply_turn_context_overrides(
        profile,
        {
            "referential_kind": "memory_synthesis",
            "needs_document_retrieval": False,
            "reason": "referential_memory_synthesis",
        },
    )
    assert out["execution_tier"] == "no_retrieval"
    assert out["evidence_mode"] == "chat_only"
    assert out["recall_k"] == 0
    assert out["rerank_enabled"] is False
    assert out["tier_contract"]["llm_temperature"] == 0.1


def test_mandatory_inherited_scope_skips_catalog_scoring():
    catalog = [
        CaseFileCatalogEntry(
            file_id="f-contract",
            filename="договор.pdf",
            summary="договор займа",
            key_points=["заём"],
        ),
        CaseFileCatalogEntry(
            file_id="f-obj",
            filename="возражения.pdf",
            summary="возражения",
            key_points=["ШАК"],
        ),
    ]
    scope = resolve_evidence_scope(
        primary_intent="drill_down",
        question="КАКИЕ КЛЮЧЕВЫЕ ВЫВОДЫ?",
        anchor_file_ids=["f-obj", "f-contract"],
        catalog=catalog,
        inherited_file_ids=["f-obj"],
    )
    assert scope is not None
    assert scope.file_ids == ("f-obj",)
    assert scope.reason == "turn_context_mandatory_inheritance"


def test_is_memory_only_for_turn_context_memory_synthesis():
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
    )
    package = SessionContextPackage(
        scope="case",
        session_key="case:c1:s1",
        prompt_block="",
        thread_state={},
        conversation_summary="",
        resolver=resolver,
        prior_answer_available=True,
    )
    meta = session_context_meta_from_package(
        package,
        turn_context={"referential_kind": "memory_synthesis"},
    )
    assert is_memory_only_turn(meta) is True


def test_scoped_deep_read_classifies_entity_pointer():
    from unittest.mock import patch

    prior = load_prior_turn_evidence_from_turns(_prior_turn())
    with patch(
        "app.services.chat.referential_query_resolver.referential_query_llm_enabled",
        return_value=False,
    ):
        resolution = resolve_turn_context(
            question="что в п. 2?",
            prior_evidence=prior,
        )
    assert resolution.referential_kind == "scoped_deep_read"
    assert resolution.needs_document_retrieval is True
    assert resolution.inherited_file_ids == ("f-obj",)


def test_load_and_resolve_end_to_end():
    resolution = load_and_resolve_turn_context(
        question="резюме",
        turns=_prior_turn(),
    )
    assert resolution.referential_kind == "memory_synthesis"
    assert resolution.inherited_file_ids == ("f-obj",)
