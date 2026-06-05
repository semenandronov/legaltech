"""Session resolver intent authority — skip LLM when HTTP intent is authoritative."""
from app.services.chat.session_context_resolver import resolve_turn_from_intent_authority
from app.services.chat.session_context_types import SessionMessageTurn, TurnRelation


def test_drill_down_intent_skips_llm_reclassification():
    turns = [
        SessionMessageTurn(message_id="u1", role="user", content="о чем документы"),
        SessionMessageTurn(message_id="a1", role="assistant", content="Обзор по 4 файлам"),
    ]
    result = resolve_turn_from_intent_authority(
        primary_intent="drill_down",
        intent_confidence=0.84,
        question="подробнее про Возражения",
        turns=turns,
        search_hits=[],
    )
    assert result is not None
    assert result.turn_relation is TurnRelation.FOLLOW_UP
    assert result.needs_document_retrieval is True
    assert result.rationale.startswith("intent_authority_")


def test_low_confidence_returns_none():
    result = resolve_turn_from_intent_authority(
        primary_intent="drill_down",
        intent_confidence=0.3,
        question="подробнее",
        turns=[],
        search_hits=[],
    )
    assert result is None


def test_referential_turn_context_blocks_intent_authority():
    turns = [
        SessionMessageTurn(message_id="u1", role="user", content="о чем документы"),
        SessionMessageTurn(message_id="a1", role="assistant", content="Обзор по 4 файлам"),
    ]
    result = resolve_turn_from_intent_authority(
        primary_intent="drill_down",
        intent_confidence=0.84,
        question="КАКИЕ КЛЮЧЕВЫЕ ВЫВОДЫ?",
        turns=turns,
        search_hits=[],
        turn_context={"referential_kind": "memory_synthesis"},
    )
    assert result is None
