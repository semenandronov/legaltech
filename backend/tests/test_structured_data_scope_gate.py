"""Scope-first structured data gate tests."""
from unittest.mock import MagicMock, patch

from app.services.chat.session_context_types import SessionMessageTurn
from app.services.chat.structured_data_scope_gate import (
    resolve_turn_file_scope,
    route_structured_data_for_turn,
)
from app.services.chat.structured_data_router import StructuredDataRouterDecision


def test_resolve_scope_attached_wins():
    scope = resolve_turn_file_scope(
        attached_file_ids=["att-1", "att-2"],
        turn_context={"inherited_file_ids": ["inh-1"]},
    )
    assert scope.file_ids == ("att-1", "att-2")
    assert scope.source == "attached"


def test_resolve_scope_inherited():
    scope = resolve_turn_file_scope(
        turn_context={"inherited_file_ids": ["doc-obj"]},
    )
    assert scope.file_ids == ("doc-obj",)
    assert scope.source == "inherited"


def test_resolve_scope_prior_statement_tabular_follow_up():
    turns = [
        SessionMessageTurn(message_id="a1", role="assistant", content="65 ops"),
    ]
    from app.services.chat.turn_context_evidence import load_prior_turn_evidence_from_turns

    prior = load_prior_turn_evidence_from_turns(turns)
    # inject turn_state via evidence on turn - use manual prior
    from app.services.chat.turn_context_evidence import PriorTurnEvidence

    prior = PriorTurnEvidence(
        message_id="a1",
        assistant_excerpt="65 ops",
        citations=(),
        retrieval_metadata={
            "turn_state": {
                "domain": "statement_analytics",
                "statement_file_id": "stmt-1",
                "operation": "count",
            }
        },
    )
    scope = resolve_turn_file_scope(
        prior_evidence=prior,
        information_need="tabular_aggregate",
    )
    assert scope.file_ids == ("stmt-1",)
    assert scope.source == "prior_statement"


@patch(
    "app.services.chat.structured_data_scope_gate._sql_capable_file_ids",
    return_value=("stmt-1",),
)
def test_scope_gate_rag_only_when_scope_is_document_files(_mock_sql):
    from app.services.chat.structured_data_scope_gate import TurnFileScope

    result = route_structured_data_for_turn(
        MagicMock(),
        case_id="case-1",
        question="подробнее про возражение",
        turn_scope=TurnFileScope(file_ids=("doc-obj",), source="inherited"),
        information_need="document_drill_down",
    )
    assert result.data_plane == "rag"
    assert result.resolver == "scope_gate_rag_only"
    assert result.rag_file_ids == ["doc-obj"]


@patch(
    "app.services.chat.structured_data_scope_gate.route_structured_data_plane",
)
@patch(
    "app.services.chat.structured_data_scope_gate._sql_capable_file_ids",
    return_value=("stmt-1",),
)
def test_scope_gate_sql_branch_when_scope_includes_statement(_mock_sql, mock_route):
    from app.services.chat.structured_data_scope_gate import TurnFileScope

    mock_route.return_value = MagicMock(
        data_plane="sql",
        statement_file_ids=["stmt-1"],
        rag_file_ids=[],
        confidence=0.9,
        reason="test",
        resolver="llm",
        information_need="tabular_aggregate",
    )
    result = route_structured_data_for_turn(
        MagicMock(),
        case_id="case-1",
        question="а в мае 2026",
        turn_scope=TurnFileScope(file_ids=("stmt-1",), source="prior_statement"),
        information_need="tabular_aggregate",
    )
    assert result.data_plane == "sql"
    mock_route.assert_called_once()
    call_kw = mock_route.call_args.kwargs
    assert call_kw["eligible_sql_file_ids"] == ["stmt-1"]


@patch(
    "app.services.chat.structured_data_scope_gate._sql_capable_file_ids",
    return_value=("stmt-1",),
)
def test_scope_gate_case_wide_document_skips_sql_llm(_mock_sql):
    from app.services.chat.structured_data_scope_gate import TurnFileScope

    result = route_structured_data_for_turn(
        MagicMock(),
        case_id="case-1",
        question="о чем возражение шашиошвили",
        turn_scope=TurnFileScope(file_ids=(), source="case_wide"),
        information_need="document_narrative",
    )
    assert result.data_plane == "rag"
    assert result.resolver == "scope_gate_rag_only"


@patch(
    "app.services.chat.structured_data_scope_gate.route_structured_data_plane",
)
@patch(
    "app.services.chat.structured_data_scope_gate._sql_capable_file_ids",
    return_value=("stmt-1",),
)
def test_scope_gate_case_wide_tabular_opens_sql_router(_mock_sql, mock_route):
    from app.services.chat.structured_data_scope_gate import TurnFileScope

    mock_route.return_value = MagicMock(
        data_plane="sql",
        statement_file_ids=["stmt-1"],
        rag_file_ids=[],
        confidence=0.95,
        reason="count",
        resolver="llm",
        information_need="tabular_aggregate",
    )
    result = route_structured_data_for_turn(
        MagicMock(),
        case_id="case-1",
        question="сколько операций в июне 2026",
        turn_scope=TurnFileScope(file_ids=(), source="case_wide"),
        information_need="tabular_aggregate",
    )
    assert result.data_plane == "sql"
    mock_route.assert_called_once()
