"""Tests for structured SQL facts and fallbacks."""

from datetime import date
from decimal import Decimal

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_facts import (
    StatementSqlFacts,
    build_facts_evidence_block,
    compose_fallback_answer,
    row_fact_from_db,
)
from app.services.chat.statement_sql_models import StatementSqlPlan


def test_count_fallback_no_pipe_format():
    facts = StatementSqlFacts(
        operation="count",
        file_label="funds_movement.pdf",
        file_id="f1",
        period_label="период 01.05.2026 — 31.05.2026",
        row_count=106,
        amount_sum=Decimal("-16781.51"),
    )
    plan = StatementSqlPlan(operation="count", statement_file_id="f1")
    text = compose_fallback_answer(
        question="сколько транзакций в мае 2026?",
        plan=plan,
        facts=facts,
    )
    assert "106 операций" in text
    assert "| #" not in text
    assert "файл:" not in text.lower()


def test_evidence_count_excludes_row_dump():
    facts = StatementSqlFacts(
        operation="count",
        file_label="выписка.pdf",
        file_id="f1",
        period_label="период 01.05.2026 — 31.05.2026",
        row_count=3,
        amount_sum=Decimal("300"),
    )
    plan = StatementSqlPlan(operation="count", statement_file_id="f1")
    block = build_facts_evidence_block(
        question="сколько операций?",
        plan=plan,
        facts=facts,
    )
    assert "Количество операций" in block
    assert "Операции для ответа" not in block


def test_evidence_list_includes_rows():
    row = CaseFileTransaction(
        id="r1",
        case_id="c1",
        file_id="f1",
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
    facts = StatementSqlFacts(
        operation="list",
        file_label="выписка.pdf",
        file_id="f1",
        period_label="май 2026",
        row_count=1,
        sample_rows=[row_fact_from_db(row)],
    )
    plan = StatementSqlPlan(operation="list", statement_file_id="f1")
    block = build_facts_evidence_block(
        question="покажи операции",
        plan=plan,
        facts=facts,
    )
    assert "оплата" in block
    assert "Операции для ответа" in block
