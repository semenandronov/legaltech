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


def test_list_fallback_includes_all_found_rows():
    rows = []
    for idx in range(12):
        row = CaseFileTransaction(
            id=f"r{idx}",
            case_id="c1",
            file_id="f1",
            global_row_index=idx,
            table_index=0,
            row_index=idx,
            operation_date=date(2026, 5, 1),
            operation_datetime_text=f"01.05.2026 10:{idx:02d}",
            amount_rub=Decimal("100"),
            amount_raw="100",
            description=f"оплата {idx}",
            row_columns={},
        )
        rows.append(row_fact_from_db(row))

    facts = StatementSqlFacts(
        operation="list",
        file_label="выписка.pdf",
        file_id="f1",
        period_label="май 2026",
        row_count=12,
        sample_rows=rows,
    )
    plan = StatementSqlPlan(operation="list", statement_file_id="f1")
    text = compose_fallback_answer(
        question="покажи операции",
        plan=plan,
        facts=facts,
    )

    assert "найдено 12 операций" in text
    assert "оплата 0" in text
    assert "оплата 11" in text
    assert "и ещё" not in text


def test_top_fallback_orders_presented_rows():
    from app.services.chat.statement_sql_facts import StatementSqlRowFact

    facts = StatementSqlFacts(
        operation="top",
        file_label="выписка.pdf",
        file_id="f1",
        period_label="весь период выписки",
        row_count=1,
        sample_rows=[
            StatementSqlRowFact(
                row_number=10,
                date_text="02.05.2026",
                amount_text="-45000",
                description="Проект",
            )
        ],
    )
    text = compose_fallback_answer(
        question="самая крупная операция",
        plan=StatementSqlPlan(operation="top", result_limit="1", statement_file_id="f1"),
        facts=facts,
    )
    assert "Самая крупная" in text
    assert "Проект" in text
    assert "-45000" in text


def test_group_evidence_and_fallback():
    from app.services.chat.statement_sql_facts import StatementSqlGroupFact

    facts = StatementSqlFacts(
        operation="group",
        file_label="выписка.pdf",
        file_id="f1",
        period_label="весь период выписки",
        row_count=5,
        group_rows=[
            StatementSqlGroupFact(
                description="Yandex",
                op_count=3,
                amount_sum_text="-300,00 ₽",
                abs_amount_sum_text="300,00 ₽",
            )
        ],
    )
    plan = StatementSqlPlan(operation="group", statement_file_id="f1")
    block = build_facts_evidence_block(question="контрагенты?", plan=plan, facts=facts)
    assert "Группы по описанию" in block
    assert "Yandex" in block
    text = compose_fallback_answer(question="контрагенты?", plan=plan, facts=facts)
    assert "Yandex" in text
    assert "3 оп." in text
