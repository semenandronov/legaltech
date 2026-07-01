"""Unified turn prep planner tests."""
from unittest.mock import patch

import pytest

from app.services.chat.turn_prep_planner import (
    TurnPrepPlannerDecision,
    _judge_result_from_planner,
    plan_case_turn_prep,
    unified_turn_prep_planner_enabled,
)
from app.services.chat.session_context_types import SessionMessageTurn


def _prior_turns() -> list[SessionMessageTurn]:
    return [
        SessionMessageTurn(message_id="u1", role="user", content="о чем возражение"),
        SessionMessageTurn(
            message_id="a1",
            role="assistant",
            content="Возражение Шиошвили против банкротства.",
            evidence={
                "citations": [{"source_id": "f-obj", "chunk_id": "c-1"}],
                "retrieval_metadata": {"file_ids": ["f-obj"]},
            },
        ),
    ]


def test_no_prior_ignores_llm_memory_synthesis():
    decision = TurnPrepPlannerDecision(
        referential_kind="memory_synthesis",
        needs_document_retrieval=False,
        data_plane="skip",
        information_need="tabular_aggregate",
        confidence=0.95,
        rationale="test",
        execution_tier="no_retrieval",
    )
    result = _judge_result_from_planner(
        question="сколько операций в июне 2026",
        has_prior=False,
        decision=decision,
    )
    assert result.referential_kind == "none"
    assert result.needs_document_retrieval is True


def test_tabular_need_overrides_memory_synthesis():
    from app.services.chat.turn_prep_planner import _apply_planner_safety_invariants

    raw = TurnPrepPlannerDecision(
        referential_kind="memory_synthesis",
        needs_document_retrieval=False,
        data_plane="skip",
        information_need="tabular_list",
        confidence=0.9,
        rationale="from chat",
        execution_tier="no_retrieval",
    )
    fixed = _apply_planner_safety_invariants(raw, question="а в мае 2026", has_prior=True)
    assert fixed.referential_kind == "none"
    assert fixed.needs_document_retrieval is True
    assert fixed.data_plane == "sql"


def test_drill_down_overrides_memory_synthesis_in_planner():
    decision = TurnPrepPlannerDecision(
        referential_kind="memory_synthesis",
        needs_document_retrieval=False,
        confidence=0.9,
        rationale="already answered",
        data_plane="skip",
        execution_tier="no_retrieval",
    )
    result = _judge_result_from_planner(
        question="подробнее про возражение",
        has_prior=True,
        decision=decision,
    )
    assert result.referential_kind == "scoped_deep_read"
    assert result.needs_document_retrieval is True
    assert result.resolver == "regex_safety"


def test_planner_sql_plane_decision():
    decision = TurnPrepPlannerDecision(
        referential_kind="none",
        needs_document_retrieval=True,
        standalone_query="сколько операций в июне 2026 в выписке т-банка",
        data_plane="sql",
        information_need="tabular_aggregate",
        confidence=0.88,
        rationale="count operations",
        execution_tier="instant",
    )
    result = _judge_result_from_planner(
        question="а в мае 2026",
        has_prior=True,
        decision=decision,
    )
    assert result.referential_kind == "none"
    assert result.needs_document_retrieval is True


@pytest.fixture
def planner_enabled(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "CASE_TURN_PREP_UNIFIED_PLANNER_ENABLED", True)


def test_plan_case_turn_prep_returns_none_when_llm_fails(planner_enabled):
    decision = TurnPrepPlannerDecision(
        referential_kind="scoped_deep_read",
        needs_document_retrieval=True,
        standalone_query="подробнее про возражение Шиошвили",
        data_plane="rag",
        information_need="document_drill_down",
        rag_file_ids=["f-obj"],
        confidence=0.9,
        rationale="drill down",
        execution_tier="standard",
    )

    class _FakeDb:
        pass

    with patch(
        "app.services.chat.turn_prep_planner.case_has_sql_statement_tables",
        return_value=False,
    ), patch(
        "app.services.chat.turn_prep_planner._invoke_unified_planner",
        return_value=decision,
    ):
        plan = plan_case_turn_prep(
            _FakeDb(),  # type: ignore[arg-type]
            case_id="case-1",
            question="подробнее про возражение",
            turns=_prior_turns(),
        )

    assert plan is not None
    assert plan.turn_context.referential_kind == "scoped_deep_read"
    assert plan.structured_route is not None
    assert plan.structured_route.data_plane == "rag"
    assert plan.information_need == "document_drill_down"
    assert plan.resolver == "unified_planner"


def test_unified_planner_disabled_returns_none(monkeypatch):
    from app.config import config

    monkeypatch.setattr(config, "CASE_TURN_PREP_UNIFIED_PLANNER_ENABLED", False)
    assert unified_turn_prep_planner_enabled() is False

    class _FakeDb:
        pass

    plan = plan_case_turn_prep(
        _FakeDb(),  # type: ignore[arg-type]
        case_id="case-1",
        question="тест",
        turns=[],
    )
    assert plan is None


def test_memory_synthesis_skips_structured_route(planner_enabled):
    decision = TurnPrepPlannerDecision(
        referential_kind="memory_synthesis",
        needs_document_retrieval=False,
        data_plane="skip",
        information_need="unknown",
        confidence=0.92,
        rationale="recap",
        execution_tier="no_retrieval",
    )

    class _FakeDb:
        pass

    with patch(
        "app.services.chat.turn_prep_planner.case_has_sql_statement_tables",
        return_value=True,
    ), patch(
        "app.services.chat.turn_prep_planner.build_statement_file_catalog",
        return_value=[],
    ), patch(
        "app.services.chat.turn_prep_planner._invoke_unified_planner",
        return_value=decision,
    ), patch(
        "app.services.case_file_transaction_service.CaseFileTransactionService.list_transaction_file_ids",
        return_value=["stmt-1"],
    ):
        plan = plan_case_turn_prep(
            _FakeDb(),  # type: ignore[arg-type]
            case_id="case-1",
            question="кратко итог",
            turns=_prior_turns(),
        )

    assert plan is not None
    assert plan.turn_context.referential_kind == "memory_synthesis"
    assert plan.structured_route is None
    assert plan.execution_tier_hint == "no_retrieval"
