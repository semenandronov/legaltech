"""Tests for statement ReAct agent wiring."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_react_agent import run_statement_react_agent
from app.services.operations_chat_service import OperationsChatService
from app.services.operations_chat_scope import OperationsChatScope


def _row() -> CaseFileTransaction:
    return CaseFileTransaction(
        id="r1",
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_datetime_text="01.01.2026",
        amount_rub=Decimal("1000"),
        amount_raw="1000",
        description="test",
        row_columns={},
        page_start=1,
    )


@patch("app.services.chat.statement_react_agent.create_react_agent")
@patch("app.services.chat.statement_react_agent.create_legal_llm")
def test_run_statement_react_agent_requires_successful_python(mock_llm, mock_create_agent):
    tool_payload = '{"ok": true, "stdout": "count 2", "stderr": ""}'

    def _invoke(_state, config=None):
        return {
            "messages": [
                HumanMessage(content="q"),
                AIMessage(content="", tool_calls=[{"name": "run_python_code", "args": {"code": "print(1)"}, "id": "1"}]),
                ToolMessage(content=tool_payload, tool_call_id="1", name="run_python_code"),
                AIMessage(content="Найдено 2 операции по признакам дробления."),
            ]
        }

    mock_create_agent.return_value.invoke.side_effect = _invoke

    patch = run_statement_react_agent(
        SimpleNamespace(),
        case_id="case-1",
        question="есть ли дробление?",
        file_id="stmt-1",
        file_label="v.pdf",
        rows=[_row(), _row()],
    )
    assert patch is not None
    assert "дробления" in patch["response"].lower()
    assert patch["statement_sql_meta"]["resolver"] == "statement_react_agent"


@patch("app.services.chat.statement_react_agent.create_react_agent")
@patch("app.services.chat.statement_react_agent.create_legal_llm")
def test_run_statement_react_agent_rejects_no_python(mock_llm, mock_create_agent):
    mock_create_agent.return_value.invoke.return_value = {
        "messages": [
            HumanMessage(content="q"),
            AIMessage(content="Ответ без кода."),
        ]
    }
    assert (
        run_statement_react_agent(
            SimpleNamespace(),
            case_id="case-1",
            question="что подозрительного?",
            file_id="stmt-1",
            file_label="v.pdf",
            rows=[_row()],
        )
        is None
    )


@patch("app.services.operations_chat_resolver.run_statement_react_agent")
@patch("app.services.operations_chat_service.resolve_turn_execution_contract")
def test_stream_analyze_open_analytics_uses_react(mock_contract, mock_react):
    from app.services.chat.turn_execution_contract import TurnExecutionContract

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
        original_question="что подозрительного в выписке?",
        effective_query="что подозрительного в выписке?",
        information_need="analytics",
        sql_plan_hints={},
        prior_turn_state=None,
        resolver="baseline",
        reason="explicit_question",
    )
    mock_react.return_value = {
        "response": "Есть признаки дробления.",
        "citations": [],
        "outbound_turn_state": {},
        "statement_sql_meta": {"resolver": "statement_react_agent"},
    }

    async def _run():
        events = []
        async for event in service.stream_analyze(
            "case-1",
            "user-1",
            "что подозрительного в выписке?",
            "stmt-1",
            SimpleNamespace(value_filters=[], row_search=""),
        ):
            events.append(event)
        return events

    events = asyncio.run(_run())
    assert any(e.get("type") == "done" for e in events)
    mock_react.assert_called_once()
