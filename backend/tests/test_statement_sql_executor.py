"""Tests for statement SQL planner executor."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_executor import (
    execute_statement_sql_plan,
    execute_statement_sql_plan_on_rows,
)
from app.services.chat.statement_sql_models import StatementSqlPlan


def _row(
    *,
    row_id: str = "r1",
    op_date: date | None = None,
    dt_text: str = "",
    amount: str = "100",
    desc: str = "test",
) -> CaseFileTransaction:
    numeric = amount.replace(" ", "").replace(",", ".")
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_date=op_date,
        operation_datetime_text=dt_text or None,
        amount_rub=Decimal(numeric),
        amount_raw=amount,
        description=desc,
        row_columns={},
        page_start=1,
    )


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.aggregate_totals")
def test_executor_count_may_ignores_spurious_on_date(mock_totals, _mock_label):
    """LLM bug: on_date=first day of month must not narrow period count."""
    from app.services.case_file_transaction_service import TransactionAggregateTotals
    from app.services.chat.statement_sql_plan_normalize import normalize_statement_sql_plan

    mock_totals.return_value = TransactionAggregateTotals(count=20, amount_sum=Decimal("0"))

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
    _, kwargs = mock_totals.call_args
    assert kwargs["on_date"] is None


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.aggregate_totals")
def test_executor_count_may_period(mock_totals, _mock_label):
    from app.services.case_file_transaction_service import TransactionAggregateTotals

    mock_totals.return_value = TransactionAggregateTotals(count=12, amount_sum=Decimal("1200"))

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
    mock_totals.assert_called_once()
    _, kwargs = mock_totals.call_args
    assert kwargs["on_date"] is None
    assert kwargs["date_from"] == date(2026, 5, 1)
    assert kwargs["date_to"] == date(2026, 5, 31)


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.query_page")
def test_executor_find_by_time(mock_page, _mock_label):
    from app.services.case_file_transaction_service import TransactionQueryPage

    rows = [
        _row(row_id="r1", op_date=date(2026, 6, 11), dt_text="11.06.2026 19:28", amount="-3100"),
        _row(row_id="r2", op_date=date(2026, 6, 11), dt_text="11.06.2026 08:00", amount="-50"),
    ]
    mock_page.return_value = TransactionQueryPage(rows=rows, total=2)
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


def test_executor_on_rows_respects_scope_and_reports_total_count():
    rows = [
        _row(
            row_id="r1",
            op_date=date(2026, 5, 1),
            dt_text="01.05.2026 10:00",
            amount="-100",
            desc="Оплата ИП Иванов",
        ),
        _row(
            row_id="r2",
            op_date=date(2026, 5, 2),
            dt_text="02.05.2026 10:00",
            amount="-200",
            desc="Оплата ИП Иванов",
        ),
    ]
    plan = StatementSqlPlan(
        operation="sum",
        description_contains="Иванов",
        amount_semantics="debit",
        statement_file_id="stmt-1",
        confidence=0.9,
    )

    result = execute_statement_sql_plan_on_rows(
        plan=plan,
        rows=rows,
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="какая сумма списаний Иванову?",
        scope_note="Ответ по отфильтрованной таблице.",
    )

    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 2
    assert result.facts.scope_note == "Ответ по отфильтрованной таблице."
    assert result.facts.amount_sum == Decimal("-300")


def test_executor_on_rows_applies_absolute_amount_threshold():
    rows = [
        _row(row_id="r1", op_date=date(2026, 3, 28), dt_text="28.03.2026 15:37", amount="-10000"),
        _row(row_id="r2", op_date=date(2026, 3, 28), dt_text="28.03.2026 13:17", amount="33180"),
        _row(row_id="r3", op_date=date(2026, 3, 28), dt_text="28.03.2026 22:49", amount="-287"),
    ]
    plan = StatementSqlPlan(
        operation="list",
        amount_compare="gt",
        amount_min="10000",
        statement_file_id="stmt-1",
        confidence=0.9,
    )

    result = execute_statement_sql_plan_on_rows(
        plan=plan,
        rows=rows,
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="найди операции где сумма была больше 10к рублей",
    )

    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 1
    assert len(result.rows) == 1
    assert result.rows[0].id == "r2"


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.query_page")
def test_executor_pushes_absolute_amount_filter_into_sql_query(mock_page, _mock_label):
    from app.services.case_file_transaction_service import TransactionQueryPage

    mock_page.return_value = TransactionQueryPage(
        rows=[
            _row(row_id="r2", op_date=date(2026, 3, 28), dt_text="28.03.2026 13:17", amount="33180"),
        ],
        total=1,
    )
    plan = StatementSqlPlan(
        operation="list",
        date_from="27.03.2026",
        date_to="27.06.2026",
        amount_compare="gt",
        amount_min="10000",
        statement_file_id="stmt-1",
        confidence=0.9,
    )

    result = execute_statement_sql_plan(
        MagicMock(),
        case_id="case-1",
        plan=plan,
        scope_file_ids=["stmt-1"],
        question="с 27 марта 2026 по 27 июня 2026 найди все операции где сумма была больше 10к рублей",
    )

    assert result.resolved is True
    _, kwargs = mock_page.call_args
    assert kwargs["abs_amount_compare"] == "gt"
    assert kwargs["abs_amount_min"] == Decimal("10000")
    assert kwargs["abs_amount_max"] is None


def test_executor_on_rows_top_orders_by_abs_amount():
    rows = [
        _row(row_id="r1", op_date=date(2026, 5, 1), dt_text="01.05.2026", amount="-100"),
        _row(row_id="r2", op_date=date(2026, 5, 2), dt_text="02.05.2026", amount="-45000"),
        _row(row_id="r3", op_date=date(2026, 5, 3), dt_text="03.05.2026", amount="33180"),
        _row(row_id="r4", op_date=date(2026, 5, 4), dt_text="04.05.2026", amount="-83"),
    ]
    plan = StatementSqlPlan(
        operation="top",
        result_limit="3",
        statement_file_id="stmt-1",
        confidence=0.95,
    )
    result = execute_statement_sql_plan_on_rows(
        plan=plan,
        rows=rows,
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="топ-3 крупнейших операций",
    )
    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 3
    assert [r.id for r in result.rows] == ["r2", "r3", "r1"]


def test_executor_on_rows_group_by_description():
    rows = [
        _row(row_id="r1", op_date=date(2026, 5, 1), amount="-100", desc="Yandex"),
        _row(row_id="r2", op_date=date(2026, 5, 2), amount="-200", desc="Yandex"),
        _row(row_id="r3", op_date=date(2026, 5, 3), amount="-50", desc="VK"),
        _row(row_id="r4", op_date=date(2026, 5, 4), amount="-1000", desc="Проект"),
    ]
    plan = StatementSqlPlan(
        operation="group",
        group_order="abs_sum",
        result_limit="2",
        statement_file_id="stmt-1",
        confidence=0.95,
    )
    result = execute_statement_sql_plan_on_rows(
        plan=plan,
        rows=rows,
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="кто основные контрагенты по сумме?",
    )
    assert result.resolved is True
    assert result.facts is not None
    assert len(result.facts.group_rows) == 2
    assert result.facts.group_rows[0].description == "Проект"
    assert result.facts.group_rows[1].description == "Yandex"
    assert result.facts.group_rows[1].op_count == 2


def test_executor_on_rows_list_reports_total_when_truncated():
    rows = [
        _row(row_id=f"r{i}", op_date=date(2026, 6, 1), amount="-10", desc=f"op {i}")
        for i in range(55)
    ]
    plan = StatementSqlPlan(
        operation="list",
        statement_file_id="stmt-1",
        confidence=0.9,
    )
    result = execute_statement_sql_plan_on_rows(
        plan=plan,
        rows=rows,
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="сколько операций в июне и в какие даты?",
    )
    assert result.resolved is True
    assert result.facts is not None
    assert result.facts.row_count == 55
    assert result.facts.truncated is True
    assert len(result.rows) == 50
