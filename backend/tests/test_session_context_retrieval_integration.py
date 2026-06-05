"""Integration checks: session context meta flows into retrieval contract."""
from app.services.chat.session_context_retrieval import (
    align_budget_profile_with_session,
    build_retrieval_query,
    question_for_retrieval,
    session_context_meta_from_package,
    should_reuse_retrieval_task,
)
from app.services.chat.session_context_types import (
    SessionContextPackage,
    SessionResolveResult,
    TurnRelation,
)


def _package(question: str, relation: TurnRelation, focus: str = "") -> SessionContextPackage:
    resolver = SessionResolveResult(
        turn_relation=relation,
        focus=focus,
        confidence=0.9,
    )
    pkg = SessionContextPackage(
        scope="case",
        session_key="case1:sess1",
        prompt_block="=== НИТЬ РАЗГОВОРА ===\ntopic",
        thread_state={"topic": "субсидиарная ответственность"},
        conversation_summary="сводка",
        resolver=resolver,
    )
    pkg.retrieval_query = build_retrieval_query(
        question,
        thread_state=pkg.thread_state,
        conversation_summary=pkg.conversation_summary,
        resolver=resolver,
    )
    return pkg


def test_meta_roundtrip_and_retrieval_nodes_read_same_query():
    pkg = _package("а про п. 3?", TurnRelation.FOLLOW_UP, focus="пункт 3")
    meta = session_context_meta_from_package(pkg)
    state = {"question": "а про п. 3?", "session_context_meta": meta}

    rq = question_for_retrieval(state)
    assert "субсидиарная" in rq
    assert "п. 3" in rq
    assert meta["retrieval_query"] == rq


def test_extract_node_reuse_guard_prevents_stale_scope():
    state = {
        "session_context_meta": {"retrieval_query": "тема\nуточнение"},
        "question": "уточнение",
    }
    assert should_reuse_retrieval_task(state, {"search_query": "тема\nуточнение"})
    assert not should_reuse_retrieval_task(state, {"search_query": "другая тема"})


def test_new_topic_retrieval_query_does_not_carry_thread():
    pkg = _package("новый вопрос про НДС", TurnRelation.NEW_TOPIC)
    assert pkg.retrieval_query == "новый вопрос про НДС"


def test_align_budget_memory_only_downgrades_tier():
    pkg = _package("какой предмет?", TurnRelation.CLARIFY_PRIOR, focus="предмет")
    pkg.prior_answer_available = True
    pkg.resolver = SessionResolveResult(
        turn_relation=TurnRelation.CLARIFY_PRIOR,
        needs_document_retrieval=False,
        focus="предмет",
        confidence=0.9,
    )
    budget = {"execution_tier": "standard", "name": "standard"}
    out = align_budget_profile_with_session(budget, pkg)
    assert out.get("execution_tier") == "no_retrieval"


def test_align_budget_restores_retrieval_when_resolver_requires_docs():
    pkg = _package("а основание?", TurnRelation.FOLLOW_UP, focus="основание")
    pkg.resolver = SessionResolveResult(
        turn_relation=TurnRelation.FOLLOW_UP,
        needs_document_retrieval=True,
        focus="основание",
        confidence=0.85,
    )
    budget = {"execution_tier": "no_retrieval", "name": "chat_only"}
    out = align_budget_profile_with_session(budget, pkg)
    assert out.get("execution_tier") == "instant"
