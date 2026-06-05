"""Session replay policy — clarify_prior without phrase triggers."""
from app.services.chat.session_context_resolver import fallback_resolve
from app.services.chat.session_context_types import (
    RelevantTurn,
    SessionMessageTurn,
    SessionResolveResult,
    TurnRelation,
)
from app.services.chat.session_replay_policy import (
    apply_corpus_retrieval_policy,
    apply_session_turn_contract,
    assistant_text_replay_quality_ok,
    enrich_resolver_with_session_signals,
    infer_clarify_from_session_signals,
    is_repeated_user_question,
    resolve_replay_target,
    task_requires_corpus_retrieval,
    turn_has_assistant_content,
    turn_has_replayable_evidence,
)
from app.services.chat.session_evidence_anchor import build_evidence_anchor_reply
from app.services.chat.session_context_service import _try_evidence_replay


def _evidence():
    return {
        "citations": [
            {
                "source_type": "court_practice",
                "quote": "Суды установили презумпцию",
                "file_name": "А19-23660/2017",
            }
        ],
    }


def test_turn_has_assistant_content_uses_transcript_not_citations():
    assert turn_has_assistant_content(
        SessionMessageTurn("a1", "assistant", "текст про суд", evidence={})
    )
    assert not turn_has_assistant_content(SessionMessageTurn("a1", "assistant", "  ", evidence=_evidence()))


def test_turn_has_replayable_evidence_requires_citations():
    assert not turn_has_replayable_evidence(
        SessionMessageTurn("a1", "assistant", "текст", evidence={})
    )
    assert turn_has_replayable_evidence(
        SessionMessageTurn("a1", "assistant", "текст", evidence=_evidence())
    )


def test_infer_clarify_without_evidence_when_assistant_text_exists():
    turns = [
        SessionMessageTurn("u0", "user", "расскажи про дело"),
        SessionMessageTurn("a0", "assistant", "Суд указал презумпцию", evidence={}),
    ]
    hits = [
        RelevantTurn("a0", "assistant", "Суд указал презумпцию", score=0.88, source="hybrid"),
    ]
    assert infer_clarify_from_session_signals(
        question="что суд сказал?",
        turns=turns,
        search_hits=hits,
    )


def test_infer_clarify_from_semantic_search_on_prior_assistant():
    turns = [
        SessionMessageTurn("u0", "user", "расскажи про дело"),
        SessionMessageTurn("a0", "assistant", "Суд указал презумпцию", evidence=_evidence()),
    ]
    hits = [
        RelevantTurn("a0", "assistant", "Суд указал презумпцию", score=0.88, source="hybrid"),
    ]
    assert infer_clarify_from_session_signals(
        question="еще раз что сказал суд?",
        turns=turns,
        search_hits=hits,
    )


def test_fallback_resolve_clarify_without_evidence_bundle():
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn(
            "a0",
            "assistant",
            "Суды установили презумпцию при непередаче документации",
            evidence={},
        ),
    ]
    hits = [
        RelevantTurn(
            "a0",
            "assistant",
            "Суды установили презумпцию",
            score=0.9,
            source="hybrid",
        ),
    ]
    res = fallback_resolve("что суд сказал?", turns, hits)
    assert res.turn_relation is TurnRelation.CLARIFY_PRIOR
    target = resolve_replay_target(turns, res, hits)
    assert target is not None
    assert "презумп" in target.content.lower()


def test_fallback_resolve_clarify_when_search_points_at_assistant():
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn("a0", "assistant", "ответ суда", evidence=_evidence()),
    ]
    hits = [RelevantTurn("a0", "assistant", "ответ суда", score=0.9, source="hybrid")]
    res = fallback_resolve("что сказал суд", turns, hits)
    assert res.turn_relation is TurnRelation.CLARIFY_PRIOR
    assert res.should_replay_prior_answer


def test_resolve_replay_without_anchor_ids():
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn("a0", "assistant", "позиция суда по делу", evidence=_evidence()),
    ]
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        focus="позиция суда",
        anchor_message_ids=[],
        confidence=0.6,
    )
    hits = [RelevantTurn("a0", "assistant", "позиция суда", score=0.85, source="hybrid")]
    target = resolve_replay_target(turns, resolver, hits)
    assert target is not None
    assert target.message_id == "a0"


def test_try_transcript_replay_without_citations():
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn("a0", "assistant", "позиция суда о презумпции", evidence={}),
    ]
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        confidence=0.5,
    )
    hits = [RelevantTurn("a0", "assistant", "позиция суда", score=0.9, source="hybrid")]
    reply = _try_evidence_replay(turns, resolver, hits)
    assert reply is not None
    assert "презумп" in reply.content.lower()
    assert reply.citations == []


def test_try_evidence_replay_short_circuit():
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn("a0", "assistant", "позиция суда по делу", evidence=_evidence()),
    ]
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        confidence=0.5,
    )
    hits = [RelevantTurn("a0", "assistant", "позиция суда", score=0.9, source="hybrid")]
    reply = _try_evidence_replay(turns, resolver, hits)
    assert reply is not None
    assert len(reply.citations) >= 1
    assert any("презумп" in (c.get("quote") or "").lower() for c in reply.citations)


def test_enrich_promotes_follow_up_when_search_supports_replay():
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn("a0", "assistant", "ответ", evidence=_evidence()),
    ]
    hits = [RelevantTurn("a0", "assistant", "ответ", score=0.8, source="hybrid")]
    base = SessionResolveResult(turn_relation=TurnRelation.FOLLOW_UP, confidence=0.9)
    enriched = enrich_resolver_with_session_signals(
        base, question="что сказал суд", turns=turns, search_hits=hits
    )
    assert enriched.turn_relation is TurnRelation.CLARIFY_PRIOR


def test_should_replay_false_when_needs_document_retrieval():
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=True,
        confidence=0.9,
    )
    assert not resolver.should_replay_prior_answer
    assert resolve_replay_target([], resolver, []) is None


def test_repeated_user_question_after_excluding_current_turn():
    turns = [
        SessionMessageTurn("u0", "user", "о чем документы"),
        SessionMessageTurn("a0", "assistant", "ответ про документы", evidence={}),
    ]
    assert is_repeated_user_question("о чем документы", turns)


def test_corpus_policy_forces_retrieval_for_multi_doc():
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.FOLLOW_UP,
        needs_document_retrieval=False,
        confidence=0.95,
    )
    out = apply_corpus_retrieval_policy(
        resolver,
        question="о чем документы",
        task_type="multi_doc_synthesis",
        corpus_size=2,
    )
    assert out.needs_document_retrieval is True
    assert "corpus_task_requires_retrieval" in out.rationale


def test_corpus_policy_skips_when_no_corpus():
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.FOLLOW_UP,
        needs_document_retrieval=False,
        confidence=0.95,
    )
    out = apply_corpus_retrieval_policy(
        resolver,
        question="о чем документы",
        task_type="multi_doc_synthesis",
        corpus_size=0,
    )
    assert out.needs_document_retrieval is False


def test_task_requires_corpus_retrieval():
    assert task_requires_corpus_retrieval("multi_doc_synthesis", corpus_size=3)
    assert not task_requires_corpus_retrieval("clarification", corpus_size=3)


def test_repeated_user_question_forces_retrieval():
    turns = [
        SessionMessageTurn("u0", "user", "о чем документы"),
        SessionMessageTurn("a0", "assistant", "ответ про документы", evidence={}),
        SessionMessageTurn("u1", "user", "о чем документы"),
    ]
    assert is_repeated_user_question("о чем документы", turns)
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        confidence=0.8,
    )
    coerced = apply_session_turn_contract(
        resolver, question="о чем документы", turns=turns
    )
    assert coerced.needs_document_retrieval is True
    assert coerced.turn_relation is TurnRelation.FOLLOW_UP
    assert not coerced.should_replay_prior_answer


def test_case_metadata_skips_replay_contract():
    turns = [
        SessionMessageTurn("u0", "user", "о чем документы"),
        SessionMessageTurn("a0", "assistant", "длинный обзор", evidence={}),
    ]
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        confidence=0.8,
    )
    coerced = apply_session_turn_contract(
        resolver, question="сколько лкументов загружено в дело", turns=turns
    )
    assert coerced.needs_document_retrieval is False
    assert not coerced.should_replay_prior_answer
    assert coerced.rationale == "case_card_metadata"


def test_replay_skips_corrupted_duplicate_text():
    chunk = "Суд установил презумпцию передачи документации. " * 4
    bad = chunk + chunk
    assert not assistant_text_replay_quality_ok(bad)
    turns = [
        SessionMessageTurn("u0", "user", "вопрос"),
        SessionMessageTurn("a0", "assistant", bad, evidence={}),
    ]
    resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        confidence=0.9,
    )
    assert resolve_replay_target(turns, resolver, []) is None
