"""Session memory router — LLM decides memory vs document retrieval."""
from app.services.chat.session_context_resolver import fallback_resolve
from app.services.chat.session_context_retrieval import (
    is_memory_only_turn,
    session_context_meta_from_package,
)
from app.services.chat.session_context_types import (
    RelevantTurn,
    SessionContextPackage,
    SessionMessageTurn,
    SessionResolveResult,
    TurnRelation,
)


def _package(resolver: SessionResolveResult, *, prior: bool = True) -> SessionContextPackage:
    return SessionContextPackage(
        scope="global",
        session_key="global:s1",
        prompt_block="",
        thread_state={},
        conversation_summary="",
        resolver=resolver,
        prior_answer_available=prior,
        prior_answer_excerpt="прошлый ответ" if prior else "",
    )


def test_is_memory_only_when_router_says_no_retrieval_on_follow_up():
    meta = session_context_meta_from_package(
        _package(
            SessionResolveResult(
                turn_relation=TurnRelation.FOLLOW_UP,
                needs_document_retrieval=False,
            )
        )
    )
    assert meta["needs_document_retrieval"] is False
    assert is_memory_only_turn(meta) is False


def test_is_memory_only_when_clarify_prior_without_retrieval():
    meta = session_context_meta_from_package(
        _package(
            SessionResolveResult(
                turn_relation=TurnRelation.CLARIFY_PRIOR,
                needs_document_retrieval=False,
            )
        )
    )
    assert is_memory_only_turn(meta) is True


def test_is_not_memory_only_when_router_requires_documents():
    meta = session_context_meta_from_package(
        _package(
            SessionResolveResult(
                turn_relation=TurnRelation.CLARIFY_PRIOR,
                needs_document_retrieval=True,
            )
        )
    )
    assert is_memory_only_turn(meta) is False


def test_is_not_memory_only_without_prior_assistant():
    meta = session_context_meta_from_package(
        _package(
            SessionResolveResult(
                turn_relation=TurnRelation.FOLLOW_UP,
                needs_document_retrieval=False,
            ),
            prior=False,
        )
    )
    assert is_memory_only_turn(meta) is False


def test_is_memory_only_for_referential_memory_synthesis():
    meta = session_context_meta_from_package(
        _package(
            SessionResolveResult(
                turn_relation=TurnRelation.CLARIFY_PRIOR,
                needs_document_retrieval=False,
            )
        ),
        turn_context={"referential_kind": "memory_synthesis"},
    )
    assert is_memory_only_turn(meta) is True


def test_fallback_clarify_sets_memory_only():
    turns = [
        SessionMessageTurn("u0", "user", "расскажи"),
        SessionMessageTurn("a0", "assistant", "Суд указал презумпцию", evidence={}),
    ]
    hits = [RelevantTurn("a0", "assistant", "Суд указал презумпцию", score=0.9)]
    res = fallback_resolve("что суд сказал?", turns, hits)
    assert res.turn_relation is TurnRelation.CLARIFY_PRIOR
    assert res.needs_document_retrieval is False
    assert res.prefers_memory_only is True


def test_fallback_new_topic_requires_documents():
    res = fallback_resolve("найди практику по новому делу", [], [])
    assert res.turn_relation is TurnRelation.NEW_TOPIC
    assert res.needs_document_retrieval is True


def test_shared_memory_only_prompt_helpers():
    from app.services.chat.session_context_retrieval import (
        MEMORY_ONLY_SYSTEM_PROMPT,
        build_memory_only_user_prompt,
    )

    assert "историю диалога" in MEMORY_ONLY_SYSTEM_PROMPT.lower()
    user = build_memory_only_user_prompt(
        question="что суд сказал?",
        session_context_prompt="=== РЕЖИМ: ОТВЕТ ИЗ ПАМЯТИ ===",
        conversation_summary="обсуждали презумпцию",
        dialog_history="Пользователь: ...\nАссистент: Суд указал ...",
    )
    assert "что суд сказал?" in user
    assert "презумп" in user
    assert "ПАМЯТИ" in user


def test_memory_only_prompt_accepts_none_summary_and_session():
    from app.services.chat.session_context_retrieval import build_memory_only_user_prompt

    user = build_memory_only_user_prompt(
        question="какие копии документов перечислены?",
        session_context_prompt=None,
        conversation_summary=None,
        dialog_history=None,
    )
    assert "какие копии документов перечислены?" in user
    assert "[нет]" in user
    assert "Сводка прошлых сообщений:" in user
