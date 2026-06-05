"""Tests for Session Context Service (semantic in-dialog memory)."""
from app.services.chat.session_context_resolver import fallback_resolve, resolve_turn_semantic
from app.services.chat.session_context_retrieval import (
    build_retrieval_query,
    question_for_retrieval,
    should_reuse_retrieval_task,
)
from app.services.chat.session_context_types import SessionResolveResult, TurnRelation
from app.services.chat.session_context_types import SessionMessageTurn, TurnRelation
from app.services.chat.session_evidence_anchor import (
    build_evidence_anchor_reply,
    slice_assistant_content,
)
from app.services.chat.session_thread_state import format_thread_state_block


def test_format_thread_state_block_includes_topic():
    block = format_thread_state_block(
        {"topic": "субсидиарная ответственность", "entities": ["ООО Альфа"]},
        "Краткая сводка диалога.",
    )
    assert "НИТЬ РАЗГОВОРА" in block
    assert "субсидиарная" in block
    assert "Краткая сводка" in block


def test_slice_assistant_content_by_focus():
    content = (
        "## Дело А19-1234/2025\n"
        "Суд указал на презумпцию добросовестности.\n\n"
        "## Дело А56-9999/2024\n"
        "Спор о взыскании задолженности.\n"
    )
    sliced = slice_assistant_content(
        content,
        focus="презумпция добросовестности",
        case_numbers=("А19-1234/2025",),
    )
    assert "презумпц" in sliced.lower()
    assert "А56-9999" not in sliced


def test_build_evidence_anchor_reply_filters_citations():
    evidence = {
        "citations": [
            {
                "source_type": "court_practice",
                "file_name": "А19-1/25",
                "quote": "презумпция добросовестности",
            },
            {
                "source_type": "court_practice",
                "file_name": "А56-9/24",
                "quote": "задолженность",
            },
        ],
        "case_numbers": ["А19-1/25", "А56-9/24"],
    }
    reply = build_evidence_anchor_reply(
        message_id="m1",
        content="## А19\nпрезумпция\n\n## А56\nдолг",
        evidence=evidence,
        focus="презумпция",
    )
    assert reply.message_id == "m1"
    assert len(reply.citations) >= 1
    assert any("презумп" in (c.get("quote") or "").lower() for c in reply.citations)


def test_fallback_resolve_uses_search_hit_anchor():
    turns = [
        SessionMessageTurn("u0", "user", "начальный вопрос"),
        SessionMessageTurn("a0", "assistant", "первый ответ"),
        SessionMessageTurn("u1", "user", "вопрос про презумпцию"),
        SessionMessageTurn("a1", "assistant", "ответ про презумпцию", evidence={"citations": []}),
    ]
    from app.services.chat.session_context_types import RelevantTurn

    hits = [
        RelevantTurn("a1", "assistant", "ответ про презумпцию", score=0.9, source="hybrid"),
    ]
    res = fallback_resolve("а подробнее про презумпцию", turns, hits)
    assert res.turn_relation in (TurnRelation.FOLLOW_UP, TurnRelation.CLARIFY_PRIOR)
    assert "a1" in res.anchor_message_ids


def test_build_retrieval_query_new_topic_is_question_only():
    rq = build_retrieval_query(
        "ст. 61 127-ФЗ",
        thread_state={"topic": "субсидиарная ответственность"},
        conversation_summary="длинная сводка",
        resolver=SessionResolveResult(turn_relation=TurnRelation.NEW_TOPIC, focus=""),
    )
    assert rq == "ст. 61 127-ФЗ"


def test_build_retrieval_query_follow_up_includes_topic_and_focus():
    rq = build_retrieval_query(
        "а подробнее про п. 3?",
        thread_state={"topic": "субсидиарная ответственность"},
        resolver=SessionResolveResult(
            turn_relation=TurnRelation.FOLLOW_UP,
            focus="пункт 3 статьи 61",
        ),
    )
    assert "субсидиарная" in rq
    assert "пункт 3" in rq
    assert "п. 3" in rq


def test_question_for_retrieval_reads_meta():
    state = {
        "question": "короткий вопрос",
        "session_context_meta": {"retrieval_query": "тема\nкороткий вопрос"},
    }
    assert question_for_retrieval(state) == "тема\nкороткий вопрос"


def test_should_reuse_retrieval_task_only_when_query_matches():
    state = {
        "session_context_meta": {"retrieval_query": "тема\nуточни"},
        "question": "уточни",
    }
    assert should_reuse_retrieval_task(state, {"search_query": "тема\nуточни"})
    assert not should_reuse_retrieval_task(state, {"search_query": "другое"})


def test_resolve_turn_semantic_disabled_returns_fallback(monkeypatch):
    from app import config

    monkeypatch.setattr(config.config, "SESSION_CONTEXT_RESOLVER_ENABLED", False)
    turns = [SessionMessageTurn("u1", "user", "тест")]
    res = resolve_turn_semantic(question="уточни", turns=turns, search_hits=[])
    assert res.confidence <= 0.5 or res.rationale == "search_fallback"
