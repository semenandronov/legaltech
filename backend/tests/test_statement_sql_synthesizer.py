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
def test_count_synthesis_is_deterministic_not_llm(mock_enabled, mock_create_llm):
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
        conversation_history=[
            {"role": "assistant", "content": "Ранее было 13 операций."},
        ],
    )
    assert result.via_llm is False
    assert "20 операций" in result.text
    assert "13" not in result.text
    mock_create_llm.assert_not_called()


@patch("app.services.llm_factory.create_llm")
@patch("app.services.chat.statement_sql_synthesizer.statement_sql_synthesis_enabled", return_value=True)
def test_synthesis_rejects_debug_pipe_output(mock_enabled, mock_create_llm):
    llm = MagicMock()
    llm.invoke.return_value = AIMessage(
        content="Примеры: файл: funds.pdf | #168 | 01.05.2026 | -100"
    )
    mock_create_llm.return_value = llm

    plan = StatementSqlPlan(operation="list", statement_file_id="stmt-1")
    execution = _execution(
        facts=_facts(operation="list", row_count=5, sample_rows=[]),
    )
    result = synthesize_statement_sql_answer(
        question="покажи операции",
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


@patch("app.services.llm_factory.create_llm")
@patch("app.services.chat.statement_sql_synthesizer.statement_sql_synthesis_enabled", return_value=True)
def test_list_synthesis_uses_llm_with_readability_prompt(_mock_enabled, mock_create_llm):
    plan = StatementSqlPlan(operation="list", statement_file_id="stmt-1")
    rows = []
    for idx in range(12):
        row = CaseFileTransaction(
            id=f"r{idx}",
            case_id="c1",
            file_id="stmt-1",
            global_row_index=idx,
            table_index=0,
            row_index=idx,
            operation_date=date(2026, 5, 1),
            operation_datetime_text=f"01.05.2026 10:{idx:02d}",
            amount_rub=Decimal("100"),
            amount_raw="100",
            description=f"операция {idx}",
            row_columns={},
        )
        rows.append(row_fact_from_db(row))
    execution = _execution(
        facts=_facts(
            operation="list",
            row_count=12,
            amount_sum=Decimal("1200"),
            sample_rows=rows,
        ),
    )

    llm = MagicMock()
    llm.invoke.return_value = AIMessage(
        content="Найдено 12 операций.\n\n1. 01.05.2026 10:00 — 100 — операция 0\n..."
    )
    mock_create_llm.return_value = llm

    result = synthesize_statement_sql_answer(
        question="покажи все операции",
        plan=plan,
        execution=execution,
    )

    assert result.via_llm is True
    mock_create_llm.assert_called_once()
    messages = llm.invoke.call_args[0][0]
    system_text = messages[0].content
    human_text = messages[1].content
    assert "удобно читать" in system_text
    assert "ОФОРМЛЕНИЕ:" in human_text
    assert "сколько и в какие даты" in human_text or "Перечисли" in human_text
    assert "единственный источник чисел" in human_text
