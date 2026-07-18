"""Tests for statement table tool-calling agent."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_models import StatementSqlPlan, StatementSqlPlanResult
from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline
from app.services.chat.statement_table_agent import run_statement_table_agent
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
)
from app.services.chat.statement_insight_tools import detect_anomalies, statement_overview
from app.services.chat.statement_table_tools import probe_description, query_statement


def _row(
    *,
    row_id: str,
    amount: str,
    desc: str,
    op_date: date = date(2026, 5, 1),
    idx: int = 0,
) -> CaseFileTransaction:
    numeric = Decimal(amount.replace(" ", "").replace(",", "."))
    if numeric < 0:
        flow = "debit"
    elif numeric > 0:
        flow = "credit"
    else:
        flow = None
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=idx,
        table_index=0,
        row_index=idx,
        operation_date=op_date,
        operation_datetime_text=op_date.strftime("%d.%m.%Y"),
        amount_rub=numeric,
        amount_raw=amount,
        description=desc,
        row_columns={},
        page_start=1,
        flow_direction=flow,
    )


def test_query_statement_top_uses_abs_amount():
    rows = [
        _row(row_id="r1", amount="-100", desc="A", idx=0),
        _row(row_id="r2", amount="-45000", desc="Проект", idx=1),
        _row(row_id="r3", amount="33180", desc="B", idx=2),
    ]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="самая крупная операция",
        rows=rows,
    )
    with bind_statement_table_session(session):
        text = query_statement.invoke({"operation": "top", "result_limit": "1"})

    assert session.last_facts is not None
    assert session.last_facts.row_count == 1
    assert session.last_execution is not None
    assert session.last_execution.rows[0].id == "r2"
    assert "Проект" in text


def test_probe_description_reports_matches():
    rows = [
        _row(row_id="r1", amount="-10", desc="Оплата Yandex Plus", idx=0),
        _row(row_id="r2", amount="-20", desc="VK Music", idx=1),
    ]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="есть ли Yandex?",
        rows=rows,
    )
    with bind_statement_table_session(session):
        payload = probe_description.invoke({"token": "Yandex"})

    assert '"match_count": 1' in payload or '"match_count":1' in payload.replace(" ", "")
    assert "ok" in payload


def test_query_statement_group_by_description():
    rows = [
        _row(row_id="r1", amount="-100", desc="Yandex", idx=0),
        _row(row_id="r2", amount="-200", desc="Yandex", idx=1),
        _row(row_id="r3", amount="-1000", desc="Проект", idx=2),
    ]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="основные контрагенты",
        rows=rows,
    )
    with bind_statement_table_session(session):
        text = query_statement.invoke(
            {"operation": "group", "group_order": "abs_sum", "result_limit": "2"}
        )

    assert session.last_facts is not None
    assert len(session.last_facts.group_rows) == 2
    assert session.last_facts.group_rows[0].description == "Проект"
    assert "Yandex" in text


@patch("app.services.chat.statement_table_agent.create_agent")
@patch("app.services.chat.statement_table_agent.create_legal_llm")
def test_run_statement_table_agent_fact_binds_answer(mock_llm, mock_create_agent):
    rows = [
        _row(row_id="r1", amount="-100", desc="A", idx=0),
        _row(row_id="r2", amount="-45000", desc="Проект", idx=1),
    ]

    def _invoke(payload, config=None):
        query_statement.invoke({"operation": "top", "result_limit": "1"})
        return {
            "messages": [
                HumanMessage(content="q"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "query_statement", "args": {}, "id": "1"}],
                ),
                ToolMessage(content="facts", tool_call_id="1", name="query_statement"),
                AIMessage(content="Самая крупная — выдумаю 13 операций."),
            ]
        }

    mock_create_agent.return_value.invoke.side_effect = _invoke
    mock_llm.return_value = MagicMock()

    db = MagicMock()
    result = run_statement_table_agent(
        db,
        case_id="case-1",
        question="самая крупная операция",
        file_id="stmt-1",
        file_label="выписка.pdf",
        rows=rows,
    )

    assert result is not None
    assert result["transaction_agent_resolved"] is True
    assert "Проект" in result["response"]
    assert "13" not in result["response"]
    assert result["statement_sql_meta"]["resolver"] == "table_agent"
    assert "query_statement" in result["statement_sql_meta"]["tool_calls"]


@patch("app.services.chat.statement_table_agent.create_agent")
@patch("app.services.chat.statement_table_agent.create_legal_llm")
def test_run_statement_table_agent_insight_answer(mock_llm, mock_create_agent):
    day = date(2026, 3, 1)
    rows = [
        _row(row_id="r1", amount="-10000", desc="Иванов", op_date=day, idx=0),
        _row(row_id="r2", amount="-11000", desc="Иванов", op_date=day, idx=1),
        _row(row_id="r3", amount="-12000", desc="Иванов", op_date=day, idx=2),
    ]

    def _invoke(payload, config=None):
        statement_overview.invoke({})
        detect_anomalies.invoke({})
        return {
            "messages": [
                HumanMessage(content="q"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "detect_anomalies", "args": {}, "id": "1"}],
                ),
                ToolMessage(content="facts", tool_call_id="1", name="detect_anomalies"),
                AIMessage(content="Вывод: есть дробление платежей Иванову — стоит проверить."),
            ]
        }

    mock_create_agent.return_value.invoke.side_effect = _invoke
    mock_llm.return_value = MagicMock()

    db = MagicMock()
    result = run_statement_table_agent(
        db,
        case_id="case-1",
        question="что подозрительного в выписке?",
        file_id="stmt-1",
        file_label="выписка.pdf",
        rows=rows,
    )

    assert result is not None
    assert result["transaction_agent_resolved"] is True
    assert "проверить" in result["response"]
    assert result["statement_sql_meta"]["resolver"] == "table_agent_insight"
    assert "detect_anomalies" in result["statement_sql_meta"]["tool_calls"]


@patch("app.services.chat.statement_table_agent.create_agent")
@patch("app.services.chat.statement_table_agent.create_legal_llm")
def test_run_statement_table_agent_insight_fallback_when_no_final_text(
    mock_llm, mock_create_agent
):
    rows = [
        _row(row_id="r1", amount="100000", desc="Зарплата", idx=0),
        _row(row_id="r2", amount="-45000", desc="ООО Ромашка", idx=1),
    ]

    def _invoke(payload, config=None):
        statement_overview.invoke({})
        return {
            "messages": [
                HumanMessage(content="q"),
                AIMessage(
                    content="",
                    tool_calls=[{"name": "statement_overview", "args": {}, "id": "1"}],
                ),
                ToolMessage(content="facts", tool_call_id="1", name="statement_overview"),
                AIMessage(content=""),
            ]
        }

    mock_create_agent.return_value.invoke.side_effect = _invoke
    mock_llm.return_value = MagicMock()

    db = MagicMock()
    result = run_statement_table_agent(
        db,
        case_id="case-1",
        question="что в выписке?",
        file_id="stmt-1",
        file_label="выписка.pdf",
        rows=rows,
    )

    assert result is not None
    # Deterministic fallback from tool summaries when model returns no prose.
    assert "Профиль выписки" in result["response"]
    assert result["statement_sql_meta"]["resolver"] == "table_agent_insight"


@patch("app.services.chat.statement_sql_pipeline.statement_table_agent_enabled", return_value=False)
@patch("app.services.chat.statement_sql_pipeline.refine_plan_with_db", side_effect=lambda db, **kw: kw["plan"])
@patch("app.services.chat.statement_sql_pipeline.synthesize_statement_sql_answer")
@patch("app.services.chat.statement_sql_pipeline.execute_statement_sql_plan")
@patch("app.services.chat.statement_sql_pipeline.plan_statement_sql")
def test_pipeline_classic_fallback_when_agent_disabled(
    mock_plan,
    mock_execute,
    mock_synthesize,
    _mock_refine,
    _mock_agent_off,
):
    from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
    from app.services.chat.statement_sql_facts import StatementSqlFacts
    from app.services.chat.statement_sql_synthesizer import StatementSqlSynthesisResult

    plan = StatementSqlPlan(operation="count", statement_file_id="stmt-1", confidence=0.9)
    mock_plan.return_value = StatementSqlPlanResult(plan=plan, resolver="llm", reason="ok")
    mock_execute.return_value = StatementSqlExecutionResult(
        resolved=True,
        facts=StatementSqlFacts(
            operation="count",
            file_label="выписка.pdf",
            file_id="stmt-1",
            period_label="май",
            row_count=12,
        ),
    )
    mock_synthesize.return_value = StatementSqlSynthesisResult(
        text="12 операций.",
        via_llm=False,
    )

    result = run_statement_sql_pipeline(
        MagicMock(),
        case_id="case-1",
        question="сколько операций в мае?",
        scope_file_ids=["stmt-1"],
    )
    assert result is not None
    assert "12 операций" in result["response"]
    mock_plan.assert_called_once()


@patch("app.services.chat.statement_sql_pipeline.run_statement_table_agent")
@patch("app.services.chat.statement_sql_pipeline.statement_table_agent_enabled", return_value=True)
def test_pipeline_prefers_table_agent(mock_enabled, mock_agent):
    mock_agent.return_value = {
        "transaction_agent_resolved": True,
        "response": "Топ: Проект −45000",
        "messages": [],
        "citations": [],
        "outbound_turn_state": {},
        "statement_sql_meta": {"resolver": "table_agent", "operation": "top"},
    }
    result = run_statement_sql_pipeline(
        MagicMock(),
        case_id="case-1",
        question="самая крупная",
        scope_file_ids=["stmt-1"],
    )
    assert result is not None
    assert result["statement_sql_meta"]["resolver"] == "table_agent"
    mock_agent.assert_called_once()
