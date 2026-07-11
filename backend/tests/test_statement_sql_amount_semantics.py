"""Tests for statement SQL amount direction (credits/debits)."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_amount_semantics import (
    amount_filter_bounds,
    infer_amount_semantics,
    is_direction_description_noise,
)
from app.services.chat.statement_sql_executor import execute_statement_sql_plan
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_normalize import apply_amount_semantics_normalization


def test_infer_debit_and_credit():
    assert infer_amount_semantics("какая сумма списаний за май") == "debit"
    assert infer_amount_semantics("сумма поступлений за май 2026") == "credit"
    assert infer_amount_semantics("сколько было пополнений") == "credit"
    assert infer_amount_semantics("сколько операций за май") == "any"


def test_direction_description_noise():
    assert is_direction_description_noise("списаний") is True
    assert is_direction_description_noise("Иванов") is False


def test_normalize_strips_direction_from_description():
    plan = apply_amount_semantics_normalization(
        StatementSqlPlan(
            operation="sum",
            date_from="01.05.2026",
            date_to="31.05.2026",
            description_contains="поступлений",
        ),
        "какая сумма поступлений за май 2026",
    )
    assert plan.description_contains == ""
    assert plan.amount_semantics == "credit"


def _row(amount: str) -> CaseFileTransaction:
    dec = Decimal(amount)
    return CaseFileTransaction(
        id="r1",
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_date=date(2026, 5, 10),
        operation_datetime_text="10.05.2026",
        amount_rub=dec,
        amount_raw=amount,
        description="test",
        row_columns={},
    )


@patch("app.services.chat.statement_sql_executor.file_display_name", return_value="выписка.pdf")
@patch("app.services.chat.statement_sql_executor.CaseFileTransactionService.aggregate_totals")
def test_executor_applies_debit_filter(mock_totals, _mock_label):
    from app.services.case_file_transaction_service import TransactionAggregateTotals

    mock_totals.return_value = TransactionAggregateTotals(
        count=2,
        amount_sum=Decimal("-150"),
    )

    plan = apply_amount_semantics_normalization(
        StatementSqlPlan(
            operation="sum",
            date_from="01.05.2026",
            date_to="31.05.2026",
            statement_file_id="stmt-1",
            description_contains="списаний",
        ),
        "какая сумма списаний за май 2026",
    )
    result = execute_statement_sql_plan(
        MagicMock(),
        case_id="case-1",
        plan=plan,
        scope_file_ids=["stmt-1"],
        question="какая сумма списаний за май 2026",
    )

    assert result.facts is not None
    assert result.facts.row_count == 2
    _, kwargs = mock_totals.call_args
    assert kwargs["max_amount"] == Decimal("-0.01")
    assert kwargs["min_amount"] is None
    assert kwargs["description_contains"] is None


def test_amount_filter_bounds():
    min_a, max_a = amount_filter_bounds("credit")
    assert min_a == Decimal("0.01")
    assert max_a is None
