from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import asyncio

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.conversation_turn_state import ConversationTurnState
from app.services.chat.turn_context_evidence import PriorTurnEvidence
from app.services.chat.turn_execution_contract import TurnExecutionContract
from app.services.operations_chat_service import OperationsChatService
from app.services.operations_chat_scope import OperationsChatScope


def _row(row_id: str = "r1") -> CaseFileTransaction:
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_datetime_text="28.03.2026 13:17",
        amount_rub=Decimal("33180"),
        amount_raw="33 180,00",
        description="Внутрибанковский перевод",
        row_columns={},
        page_start=1,
    )


@dataclass(frozen=True)
class _UiState:
    value_filters: list
    row_search: str = ""


@patch("app.services.operations_chat_service.resolve_operations_chat")
@patch("app.services.operations_chat_service.resolve_turn_execution_contract")
def test_stream_analyze_routes_through_resolver(
    mock_contract,
    mock_resolve,
):
    service = OperationsChatService(SimpleNamespace())
    service._get_case_for_user = lambda case_id, user_id: SimpleNamespace(id=case_id)  # type: ignore[method-assign]
    service._load_scope = lambda **_: OperationsChatScope(  # type: ignore[method-assign]
        file_id="stmt-1",
        file_label="stmt.pdf",
        total_rows=1,
        filtered_rows=[_row()],
        column_headers=[],
        row_search="",
        active_filters=0,
    )
    service._load_prior_turn_evidence = lambda **_: None  # type: ignore[method-assign]
    service._load_conversation_history = lambda **_: []  # type: ignore[method-assign]
    service._persist_turn = lambda *args, **kwargs: None  # type: ignore[method-assign]

    mock_contract.return_value = TurnExecutionContract(
        original_question="по всей выписке найди операции больше 10к",
        effective_query="по всей выписке найди операции где сумма была больше 10к рублей",
        information_need="tabular_list",
        sql_plan_hints={"operation": "list", "amount_compare": "gt", "amount_min": "10000"},
        prior_turn_state=None,
        resolver="baseline",
        reason="explicit_question",
    )
    mock_resolve.return_value = (
        {
            "response": "Найдена одна операция.",
            "citations": [],
            "outbound_turn_state": {},
            "statement_sql_meta": {"resolver": "operations_sql_scope", "row_count": 1},
        },
        "factual_list",
    )

    async def _run():
        events = []
        async for event in service.stream_analyze(
            "case-1",
            "user-1",
            "по всей выписке найди операции больше 10к",
            "stmt-1",
            _UiState(value_filters=[], row_search=""),
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert any(event.get("type") == "done" for event in events)
    _, kwargs = mock_resolve.call_args
    assert kwargs["question"] == "по всей выписке найди операции где сумма была больше 10к рублей"
    assert kwargs["sql_hints"]["amount_compare"] == "gt"
    assert kwargs["sql_hints"]["amount_min"] == "10000"
    assert kwargs["rows"] is not None
    assert len(kwargs["rows"]) == 1


def _prior_filtered_scope_evidence() -> PriorTurnEvidence:
    state = ConversationTurnState(
        domain="statement_analytics",
        statement_file_id="stmt-1",
        operation="list",
        amount_compare="gt",
        amount_min="10000",
        ui_scope_had_filters=True,
        structured_data_plane="sql",
        topic_file_ids=("stmt-1",),
    )
    return PriorTurnEvidence(
        message_id="a-prior",
        assistant_excerpt="Найдено 10 операций больше 10 000 ₽.",
        citations=(),
        retrieval_metadata={"turn_state": state.to_dict()},
    )


@patch("app.services.operations_chat_service.resolve_operations_chat")
@patch("app.services.operations_chat_service.resolve_turn_execution_contract")
def test_stream_analyze_resets_prior_context_when_ui_scope_expands(
    mock_contract,
    mock_resolve,
):
    service = OperationsChatService(SimpleNamespace())
    service._get_case_for_user = lambda case_id, user_id: SimpleNamespace(id=case_id)  # type: ignore[method-assign]
    service._load_scope = lambda **_: OperationsChatScope(  # type: ignore[method-assign]
        file_id="stmt-1",
        file_label="stmt.pdf",
        total_rows=335,
        filtered_rows=[_row(f"r{i}") for i in range(335)],
        column_headers=[],
        row_search="",
        active_filters=0,
    )
    service._load_prior_turn_evidence = lambda **_: _prior_filtered_scope_evidence()  # type: ignore[method-assign]
    service._load_conversation_history = lambda **_: [  # type: ignore[method-assign]
        {"role": "user", "content": "операции больше 10к"},
        {"role": "assistant", "content": "Найдено 10 операций."},
    ]
    service._persist_turn = lambda *args, **kwargs: None  # type: ignore[method-assign]

    mock_contract.return_value = TurnExecutionContract(
        original_question="что за операции?",
        effective_query="что за операции?",
        information_need="unknown",
        sql_plan_hints={},
        prior_turn_state=None,
        resolver="baseline",
        reason="explicit_question",
    )
    mock_resolve.return_value = (
        {
            "response": "Все операции выписки.",
            "citations": [],
            "outbound_turn_state": {"domain": "statement_analytics", "operation": "list"},
            "statement_sql_meta": {"resolver": "table_agent", "row_count": 5},
        },
        "unknown",
    )

    async def _run():
        events = []
        async for event in service.stream_analyze(
            "case-1",
            "user-1",
            "что за операции?",
            "stmt-1",
            _UiState(value_filters=[], row_search=""),
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())

    assert any(event.get("type") == "done" for event in events)
    mock_contract.assert_called_once()
    assert mock_contract.call_args.kwargs["prior_evidence"] is None
    _, kwargs = mock_resolve.call_args
    assert kwargs["conversation_history"] == []
    assert len(kwargs["rows"]) == 335
