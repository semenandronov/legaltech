from unittest.mock import patch

from app.services.chat.conversation_turn_state import ConversationTurnState
from app.services.chat.turn_delta_resolver import resolve_turn_delta


@patch("app.services.chat.turn_delta_resolver.turn_delta_llm_enabled", return_value=False)
def test_follow_up_amounts_keeps_list_scope_for_prior_matches(_mock_enabled):
    prior = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id="stmt-1",
        operation="list",
        description_contains="YANDEX",
    )

    delta = resolve_turn_delta(
        question="на какие суммы",
        prior_turn_state=prior,
        referential_kind="none",
        prior_evidence=None,
    )

    assert delta.sql_plan_hints["operation"] == "list"
    assert delta.sql_plan_hints["description_contains"] == "YANDEX"


@patch("app.services.chat.turn_delta_resolver.turn_delta_llm_enabled", return_value=False)
def test_follow_up_detail_converts_aggregate_to_list(_mock_enabled):
    prior = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id="stmt-1",
        operation="count",
        amount_semantics="credit",
    )

    delta = resolve_turn_delta(
        question="подробнее",
        prior_turn_state=prior,
        referential_kind="scoped_deep_read",
        prior_evidence=None,
    )

    assert delta.sql_plan_hints["operation"] == "list"
    assert delta.sql_plan_hints["amount_semantics"] == "credit"


@patch("app.services.chat.turn_delta_resolver.turn_delta_llm_enabled", return_value=False)
def test_follow_up_whole_statement_clears_period_inheritance(_mock_enabled):
    prior = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id="stmt-1",
        operation="list",
        date_from="02.06.2026",
        date_to="05.06.2026",
    )

    delta = resolve_turn_delta(
        question="по всей выписке найди операции больше 10к",
        prior_turn_state=prior,
        referential_kind="scoped_deep_read",
        prior_evidence=None,
    )

    assert "date_from" not in delta.sql_plan_hints
    assert "date_to" not in delta.sql_plan_hints
