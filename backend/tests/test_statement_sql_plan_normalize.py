"""Tests for statement SQL plan normalization."""

from datetime import date

from app.services.chat.statement_sql_plan_normalize import (
    clears_statement_period,
    effective_query_dates,
    infer_amount_hint_from_question,
    infer_period_from_question,
    normalize_statement_sql_plan,
)
from app.services.chat.statement_sql_models import StatementSqlPlan


def test_infer_calendar_month_from_question():
    hint = infer_period_from_question("кол-во операций в мае по банковской выписке?")
    assert hint.kind == "calendar_month"
    assert hint.date_from == date(2026, 5, 1)
    assert hint.date_to == date(2026, 5, 31)


def test_infer_single_day_from_dmy():
    hint = infer_period_from_question("операция 11.06.2026 в 19:28")
    assert hint.kind == "single_day"
    assert hint.on_date == date(2026, 6, 11)


def test_infer_named_date_range_from_question():
    hint = infer_period_from_question("с 27 марта 2026 по 27 июня 2026 найди операции")
    assert hint.kind == "date_range"
    assert hint.date_from == date(2026, 3, 27)
    assert hint.date_to == date(2026, 6, 27)


def test_clears_statement_period_for_whole_statement():
    assert clears_statement_period("по всей выписке найди операции больше 10к") is True


def test_infer_amount_hint_for_greater_than():
    hint = infer_amount_hint_from_question("найди операции где сумма была больше 10к рублей")
    assert hint.compare == "gt"
    assert hint.amount_min == "10000"


def test_normalize_clears_on_date_when_llm_set_month_range_and_first_day():
    """Reproduces production bug: on_date=01.05 + range May → only 4 ops on May 1."""
    raw = StatementSqlPlan(
        operation="count",
        on_date="01.05.2026",
        date_from="01.05.2026",
        date_to="31.05.2026",
        statement_file_id="f1",
        confidence=1.0,
    )
    plan = normalize_statement_sql_plan(
        raw,
        "кол-во операций в мае по банковской выписке?",
    )
    on_d, d_from, d_to = effective_query_dates(plan)
    assert on_d is None
    assert d_from == date(2026, 5, 1)
    assert d_to == date(2026, 5, 31)
    assert plan.on_date == ""


def test_normalize_keeps_single_day_for_explicit_date_question():
    plan = normalize_statement_sql_plan(
        StatementSqlPlan(
            operation="find",
            on_date="11.06.2026",
            date_from="01.06.2026",
            date_to="30.06.2026",
            time_hint="19:28",
            statement_file_id="f1",
            confidence=0.9,
        ),
        "что было 11.06.2026 в 19:28",
    )
    on_d, d_from, d_to = effective_query_dates(plan)
    assert on_d == date(2026, 6, 11)
    assert d_from is None
    assert d_to is None


def test_executor_query_dates_multi_day_range_no_on_date():
    plan = StatementSqlPlan(
        operation="count",
        on_date="01.05.2026",
        date_from="01.05.2026",
        date_to="31.05.2026",
        statement_file_id="f1",
        confidence=1.0,
    )
    plan = normalize_statement_sql_plan(plan, "сколько операций за май 2026")
    on_d, d_from, d_to = effective_query_dates(plan)
    assert on_d is None
    assert d_from == date(2026, 5, 1)
    assert d_to == date(2026, 5, 31)


def test_normalize_adds_amount_filter_from_question():
    plan = normalize_statement_sql_plan(
        StatementSqlPlan(
            operation="list",
            statement_file_id="f1",
            confidence=1.0,
        ),
        "по всей выписке найди операции где сумма была больше 10к рублей",
    )
    assert plan.amount_compare == "gt"
    assert plan.amount_min == "10000"


def test_apply_sql_plan_hints_does_not_reinject_stale_amount_threshold():
    """New topic left amount empty — prior >9999 must not be force-filled."""
    from app.services.chat.statement_sql_plan_normalize import apply_sql_plan_hints

    plan = StatementSqlPlan(
        operation="count",
        description_contains="Yandex",
        statement_file_id="f1",
        confidence=0.95,
    )
    out = apply_sql_plan_hints(
        plan,
        {
            "operation": "list",
            "amount_compare": "gt",
            "amount_min": "9999",
            "description_contains": "OLD",
            "date_from": "01.05.2026",
            "date_to": "31.05.2026",
        },
    )
    assert out.amount_compare in ("", "none") or not str(out.amount_compare).strip()
    assert not str(out.amount_min or "").strip()
    assert out.description_contains == "Yandex"  # plan already set — do not overwrite
    assert out.date_from == "01.05.2026"
    assert out.date_to == "31.05.2026"


def test_apply_sql_plan_hints_fills_description_for_underspecified_follow_up():
    from app.services.chat.statement_sql_plan_normalize import apply_sql_plan_hints

    plan = StatementSqlPlan(
        operation="list",
        statement_file_id="f1",
        confidence=0.9,
    )
    out = apply_sql_plan_hints(
        plan,
        {"description_contains": "YANDEX", "amount_semantics": "debit"},
    )
    assert out.description_contains == "YANDEX"
    assert out.amount_semantics == "debit"


def test_normalize_upgrades_count_to_list_when_dates_requested():
    plan = normalize_statement_sql_plan(
        StatementSqlPlan(
            operation="count",
            date_from="01.06.2026",
            date_to="30.06.2026",
            statement_file_id="f1",
            confidence=0.9,
        ),
        "сколько операций в июне и в какие даты?",
    )
    assert plan.operation == "list"


def test_normalize_sets_top_limit_for_largest_one():
    plan = normalize_statement_sql_plan(
        StatementSqlPlan(
            operation="top",
            statement_file_id="f1",
            confidence=0.9,
        ),
        "какая самая крупная операция?",
    )
    assert plan.result_limit == "1"
    assert plan.resolved_result_limit() == 1


def test_normalize_sets_top_n_from_question():
    plan = normalize_statement_sql_plan(
        StatementSqlPlan(
            operation="top",
            statement_file_id="f1",
            confidence=0.9,
        ),
        "покажи топ-5 операций",
    )
    assert plan.result_limit == "5"
