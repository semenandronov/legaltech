"""Tests for LLM synthesis of statement SQL answers."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
from app.services.chat.statement_sql_facts import StatementSqlFacts, row_fact_from_db
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_synthesizer import (
    build_sql_evidence_block,
    synthesize_statement_sql_answer,
)


def _facts(**kwargs) -> StatementSqlFacts:
    defaults = {
        "operation": "count",
        "file_label": "выписка.pdf",
        "file_id": "stmt-1",
        "period_label": "период 01.05.2026 — 31.05.2026",
        "row_count": 3,
        "amount_sum": Decimal("300"),
    }
    defaults.update(kwargs)
    return StatementSqlFacts(**defaults)


def _execution(**kwargs) -> StatementSqlExecutionResult:
    facts = kwargs.pop("facts", _facts())
    return StatementSqlExecutionResult(resolved=True, facts=facts, **kwargs)


@patch("app.services.chat.statement_sql_synthesizer.statement_sql_synthesis_enabled", return_value=False)
def test_synthesis_disabled_returns_minimal_fallback(_mock_enabled):
    plan = StatementSqlPlan(operation="count", statement_file_id="stmt-1")
    execution = _execution()
    result = synthesize_statement_sql_answer(
        question="сколько операций в мае?",
        plan=plan,
        execution=execution,
    )
    assert result.via_llm is False
    assert "3 операций" in result.text
    assert "| #" not in result.text


@patch("app.services.llm_factory.create_llm")
@patch("app.services.chat.statement_sql_synthesizer.statement_sql_synthesis_enabled", return_value=True)
def test_synthesis_uses_lite_llm(mock_enabled, mock_create_llm):
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(
        content="В мае 2026 года по выписке зафиксировано 20 операций на общую сумму 2 000 ₽."
    )
    mock_create_llm.return_value = llm

    plan = StatementSqlPlan(
        operation="count",
        date_from="01.05.2026",
        date_to="31.05.2026",
        statement_file_id="stmt-1",
    )
    execution = _execution(
        facts=_facts(row_count=20, amount_sum=Decimal("2000")),
    )
    result = synthesize_statement_sql_answer(
        question="кол-во операций в мае по банковской выписке?",
        plan=plan,
        execution=execution,
    )
    assert result.via_llm is True
    assert "20 операций" in result.text
    mock_create_llm.assert_called_once()
    llm.invoke.assert_called_once()


@patch("app.services.llm_factory.create_llm")
@patch("app.services.chat.statement_sql_synthesizer.statement_sql_synthesis_enabled", return_value=True)
def test_synthesis_rejects_debug_pipe_output(mock_enabled, mock_create_llm):
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(
        content="Примеры: файл: funds.pdf | #168 | 01.05.2026 | -100"
    )
    mock_create_llm.return_value = llm

    plan = StatementSqlPlan(operation="count", statement_file_id="stmt-1")
    execution = _execution(facts=_facts(row_count=5))
    result = synthesize_statement_sql_answer(
        question="сколько операций?",
        plan=plan,
        execution=execution,
    )
    assert result.via_llm is False
    assert "| #" not in result.text


def test_evidence_block_includes_aggregates():
    row = CaseFileTransaction(
        id="r1",
        case_id="c1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_date=date(2026, 5, 1),
        operation_datetime_text="01.05.2026 10:00",
        amount_rub=Decimal("100"),
        amount_raw="100",
        description="оплата",
        row_columns={},
    )
    plan = StatementSqlPlan(operation="count", statement_file_id="stmt-1")
    facts = _facts(sample_rows=[row_fact_from_db(row)])
    execution = StatementSqlExecutionResult(resolved=True, facts=facts, rows=[row])
    block = build_sql_evidence_block(plan=plan, execution=execution, question="сколько?")
    assert "Количество операций" in block
    assert "выписка.pdf" in block
