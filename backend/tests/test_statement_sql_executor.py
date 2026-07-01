"""Tests for statement SQL planner executor."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_executor import execute_statement_sql_plan
from app.services.chat.statement_sql_models import StatementSqlPlan


def _row(
    *,
    row_id: str = "r1",
    op_date: date | None = None,
    dt_text: str = "",
    amount: str = "100",
    desc: str = "test",
) -> CaseFileTransaction:
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_date=op_date,
        operation_datetime_text=dt_text or None,
        amount_rub=Decimal("100.00"),
        amount_raw=amount,
        description=desc,
        row_columns={},
        page_start=1,
    )


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.query")
def test_executor_count_may_ignores_spurious_on_date(mock_query, _mock_label):
    """LLM bug: on_date=first day of month must not narrow period count."""
    may_rows = [
        _row(row_id=f"r{i}", op_date=date(2026, 5, i + 1), dt_text=f"{i+1:02d}.05.2026 10:00")
        for i in range(20)
    ]
    mock_query.return_value = may_rows

    from app.services.chat.statement_sql_plan_normalize import normalize_statement_sql_plan

    plan = normalize_statement_sql_plan(
        StatementSqlPlan(
            operation="count",
            on_date="01.05.2026",
            date_from="01.05.2026",
            date_to="31.05.2026",
            statement_file_id="stmt-1",
            confidence=1.0,
        ),
        "кол-во операций в мае по банковской выписке?",
    )
    result = execute_statement_sql_plan(
        MagicMock(),
        case_id="case-1",
        plan=plan,
        scope_file_ids=["stmt-1"],
    )

    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 20
    _, kwargs = mock_query.call_args
    assert kwargs["on_date"] is None


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.query")
def test_executor_count_may_period(mock_query, _mock_label):
    may_rows = [
        _row(row_id=f"r{i}", op_date=date(2026, 5, i + 1), dt_text=f"0{i+1}.05.2026 10:00")
        for i in range(12)
    ]
    mock_query.return_value = may_rows

    plan = StatementSqlPlan(
        operation="count",
        date_from="01.05.2026",
        date_to="31.05.2026",
        statement_file_id="stmt-1",
        confidence=0.95,
    )
    result = execute_statement_sql_plan(
        MagicMock(),
        case_id="case-1",
        plan=plan,
        scope_file_ids=["stmt-1"],
    )

    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 12
    assert "период" in result.facts.period_label
    assert result.facts.file_label == "выписка.pdf"
    mock_query.assert_called_once()
    _, kwargs = mock_query.call_args
    assert kwargs["on_date"] is None
    assert kwargs["date_from"] == date(2026, 5, 1)
    assert kwargs["date_to"] == date(2026, 5, 31)


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.query")
def test_executor_find_by_time(mock_query, _mock_label):
    mock_query.return_value = [
        _row(row_id="r1", op_date=date(2026, 6, 11), dt_text="11.06.2026 19:28", amount="-3100"),
        _row(row_id="r2", op_date=date(2026, 6, 11), dt_text="11.06.2026 08:00", amount="-50"),
    ]
    plan = StatementSqlPlan(
        operation="find",
        on_date="11.06.2026",
        time_hint="19:28",
        statement_file_id="stmt-1",
        confidence=0.9,
    )
    result = execute_statement_sql_plan(
        MagicMock(),
        case_id="case-1",
        plan=plan,
        scope_file_ids=["stmt-1"],
    )

    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 1
    assert len(result.rows) == 1


@patch(
    "app.services.chat.case_transaction_agent.run_statement_sql_pipeline",
    return_value={
        "transaction_agent_resolved": True,
        "response": "По справке за период 01.05.2026 — 31.05.2026: 47 операций.",
        "messages": [],
        "citations": [],
        "rag_context": "",
    },
)
@patch(
    "app.services.chat.case_transaction_agent.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["stmt-1"],
)
@patch("app.services.chat.case_transaction_agent.feature_enabled", return_value=True)
def test_case_agent_uses_pipeline_first(_mock_feature, _mock_ids, mock_pipeline):
    from app.services.chat.case_transaction_agent import run_case_transaction_agent

    db = MagicMock()
    result = run_case_transaction_agent(
        db,
        case_id="case-1",
        question="сколько операций в мае",
        statement_scope_file_ids=["stmt-1"],
    )
    assert result is not None
    assert result["transaction_agent_resolved"] is True
    assert "47 операций" in result["response"]
    mock_pipeline.assert_called_once()
