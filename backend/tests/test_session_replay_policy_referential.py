"""Session replay policy — clarify vs scoped retrieval disambiguation."""
from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.session_replay_policy import infer_clarify_from_session_signals


def test_deictic_follow_up_is_not_clarify_prior():
    turns = [
        SessionMessageTurn("u1", "user", "расскажи про возражение"),
        SessionMessageTurn(
            "a1",
            "assistant",
            "Сумма требований 1,2 млн руб.",
            evidence={},
        ),
    ]
    assert infer_clarify_from_session_signals(
        question="А эта сумма — откуда?",
        turns=turns,
        search_hits=[],
    ) is False


def test_memory_synthesis_is_clarify_prior():
    turns = [
        SessionMessageTurn("u1", "user", "расскажи"),
        SessionMessageTurn("a1", "assistant", "Обзор документов", evidence={}),
    ]
    assert infer_clarify_from_session_signals(
        question="ключевые выводы?",
        turns=turns,
        search_hits=[],
    ) is True
