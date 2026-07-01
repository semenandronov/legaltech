"""Tests for conversation turn state and execution contract."""
from app.services.chat.conversation_turn_state import (
    ConversationTurnState,
    load_prior_turn_state,
    merge_sql_plan_hints,
    turn_state_from_sql_plan,
)
from app.services.chat.structured_data_capability import enforce_data_plane_capability
from app.services.chat.turn_context_evidence import CitationAnchor, PriorTurnEvidence
from app.services.chat.turn_delta_resolver import resolve_turn_delta
from app.services.chat.turn_execution_contract import resolve_turn_execution_contract


def _prior_sql_state() -> PriorTurnEvidence:
    return PriorTurnEvidence(
        message_id="a1",
        assistant_excerpt="В мае 2026 года было совершено 106 операций.",
        citations=(),
        retrieval_metadata={
            "turn_state": {
                "domain": "statement_analytics",
                "statement_file_id": "file-1",
                "operation": "count",
                "date_from": "01.05.2026",
                "date_to": "31.05.2026",
                "structured_data_plane": "sql",
            }
        },
    )


def test_load_prior_turn_state_from_evidence():
    state = load_prior_turn_state(_prior_sql_state())
    assert state is not None
    assert state.operation == "count"
    assert state.date_from == "01.05.2026"


def test_merge_sql_plan_hints_flips_count_to_sum():
    prior = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id="file-1",
        operation="count",
        date_from="01.05.2026",
        date_to="31.05.2026",
    )
    hints = merge_sql_plan_hints(prior, operation_override="sum")
    assert hints["operation"] == "sum"
    assert hints["date_from"] == "01.05.2026"


def test_deterministic_delta_for_metric_follow_up():
    prior = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id="file-1",
        operation="count",
        date_from="01.05.2026",
        date_to="31.05.2026",
    )
    from unittest.mock import patch

    with patch(
        "app.services.chat.turn_delta_resolver.turn_delta_llm_enabled",
        return_value=False,
    ):
        result = resolve_turn_delta(
            question="на какую сумму",
            prior_turn_state=prior,
            referential_kind="scoped_deep_read",
            prior_evidence=_prior_sql_state(),
        )
    assert result.sql_plan_hints.get("operation") == "sum"
    assert "01.05.2026" in result.effective_query or "file-1" in result.effective_query
    assert result.information_need == "tabular_aggregate"
    assert result.resolver == "deterministic_prior_state"


def test_execution_contract_inherits_sql_scope():
    from unittest.mock import patch

    with patch(
        "app.services.chat.turn_delta_resolver.turn_delta_llm_enabled",
        return_value=False,
    ):
        contract = resolve_turn_execution_contract(
            question="на какую сумму",
            turn_context={
                "referential_kind": "scoped_deep_read",
                "standalone_query": "на какую сумму",
                "original_question": "на какую сумму",
            },
            prior_evidence=_prior_sql_state(),
        )
    assert contract.effective_query != "на какую сумму"
    assert contract.sql_plan_hints.get("operation") == "sum"


def test_capability_narrative_overrides_sql():
    plane, reason = enforce_data_plane_capability(
        "sql",
        "document_narrative",
        has_sql_tables=True,
    )
    assert plane == "rag"
    assert "narrative" in reason


def test_capability_tabular_prefers_sql():
    plane, _ = enforce_data_plane_capability(
        "rag",
        "tabular_aggregate",
        has_sql_tables=True,
    )
    assert plane == "sql"


def test_turn_state_from_sql_plan():
    from app.services.chat.statement_sql_models import StatementSqlPlan

    plan = StatementSqlPlan(
        operation="sum",
        date_from="01.05.2026",
        date_to="31.05.2026",
        statement_file_id="f1",
    )
    state = turn_state_from_sql_plan(plan=plan, file_id="f1")
    assert state.operation == "sum"
    assert state.domain == "statement_analytics"
