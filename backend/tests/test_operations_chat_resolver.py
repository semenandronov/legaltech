"""Operations chat resolver — ReAct-only path."""
from types import SimpleNamespace
from unittest.mock import patch

from app.services.operations_chat_resolver import resolve_operations_chat


@patch("app.services.operations_chat_resolver.run_statement_react_agent")
def test_resolve_always_calls_react_for_counterparty(mock_react):
    mock_react.return_value = {"response": "ok", "statement_sql_meta": {}}
    db = SimpleNamespace()
    patch, intent = resolve_operations_chat(
        db,
        case_id="c1",
        question="были ли операции с Андроновым?",
        file_id="f1",
        file_label="v.pdf",
        rows=[],
        scope_note="",
        sql_hints={},
        prior_state=None,
        conversation_history=[],
        ui_scope_had_filters=False,
    )
    assert intent == "counterparty_lookup"
    mock_react.assert_called_once()
    assert patch == mock_react.return_value


@patch("app.services.operations_chat_resolver.run_statement_react_agent")
def test_resolve_always_calls_react_for_factual_list(mock_react):
    mock_react.return_value = None
    resolve_operations_chat(
        SimpleNamespace(),
        case_id="c1",
        question="найди операции больше 10к",
        file_id="f1",
        file_label="v.pdf",
        rows=[],
        scope_note="",
        sql_hints={"amount_min": "10000"},
        prior_state=None,
        conversation_history=[],
        ui_scope_had_filters=False,
    )
    mock_react.assert_called_once()
