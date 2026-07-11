"""Tests for statement SQL plan validation and value grounding."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_sql_models import StatementSqlPlan
from app.services.chat.statement_sql_plan_validate import (
    extract_content_tokens,
    is_description_filter_noise,
    sanitize_description_contains,
)
from app.services.chat.statement_sql_value_grounding import (
    RowsDescriptionMatchProbe,
    ground_description_filter,
    refine_plan_with_rows,
)


def _row(*, description: str, amount: str = "100") -> CaseFileTransaction:
    return CaseFileTransaction(
        id="r1",
        case_id="c1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_datetime_text="01.05.2026 10:00",
        amount_rub=Decimal(amount),
        amount_raw=amount,
        description=description,
        row_columns={"Описание операции": description},
    )


def test_description_filter_noise_rejects_query_scaffolding():
    assert is_description_filter_noise("операций")
    assert is_description_filter_noise("сколько")
    assert is_description_filter_noise("платежей")
    assert is_description_filter_noise("списаний")
    assert not is_description_filter_noise("Yandex")
    assert not is_description_filter_noise("Иванов")
    assert not is_description_filter_noise("VK")
    assert not is_description_filter_noise("МТС")


def test_sanitize_keeps_short_brand_codes():
    plan = StatementSqlPlan(
        operation="count",
        description_contains="VK",
        confidence=0.9,
    )
    assert sanitize_description_contains(plan).description_contains == "VK"


def test_extract_content_tokens_keeps_short_codes_drops_particles():
    tokens = extract_content_tokens(
        "были ли операции с VK и если да то сколько и в какие даты"
    )
    lowered = {t.lower() for t in tokens}
    assert "vk" in lowered
    assert "ли" not in lowered
    assert "да" not in lowered
    assert "то" not in lowered
    assert "если" not in lowered
    assert "сколько" not in lowered
    assert "операции" not in lowered


def test_grounding_keeps_vk_when_present_in_data():
    rows = [_row(description="Оплата VK*1234*ADS Moskva RUS")]
    plan = StatementSqlPlan(
        operation="list",
        description_contains="VK",
        confidence=0.95,
    )
    grounded = ground_description_filter(
        plan,
        question="были ли операции с VK и если да то сколько и в какие даты",
        probe=RowsDescriptionMatchProbe(rows),
    )
    assert grounded.description_contains == "VK"


def test_grounding_probe_ignores_vk_embedded_in_other_token():
    rows = [_row(description="Оплата AVK STORE Moskva RUS")]
    assert RowsDescriptionMatchProbe(rows).count("VK") == 0
    plan = StatementSqlPlan(
        operation="count",
        description_contains="VK",
        confidence=0.9,
    )
    grounded = ground_description_filter(
        plan,
        question="сколько операций VK",
        probe=RowsDescriptionMatchProbe(rows),
    )
    # No real VK token in data → clear unmatched needle
    assert grounded.description_contains == ""


def test_sanitize_clears_noise_description_contains():
    plan = StatementSqlPlan(
        operation="count",
        description_contains="операций",
        confidence=0.9,
    )
    cleaned = sanitize_description_contains(plan)
    assert cleaned.description_contains == ""


def test_extract_content_tokens_keeps_entity_drops_scaffolding():
    tokens = extract_content_tokens("сколько операций Yandex за май")
    lowered = {t.lower() for t in tokens}
    assert "yandex" in lowered
    assert "сколько" not in lowered
    assert "операций" not in lowered


def test_grounding_keeps_matching_plan_needle():
    rows = [_row(description="Оплата в YANDEX*4121*GO Moskva RUS")]
    plan = StatementSqlPlan(
        operation="count",
        description_contains="Yandex",
        confidence=0.9,
    )
    grounded = ground_description_filter(
        plan,
        question="сколько операций Yandex",
        probe=RowsDescriptionMatchProbe(rows),
    )
    assert grounded.description_contains.lower() == "yandex"


def test_grounding_recovers_yandex_when_plan_has_noise():
    rows = [
        _row(description="Оплата в YANDEX*4121*GO Moskva RUS"),
        _row(description="Оплата в YANDEX*5411*LAVKA Moskva RUS", amount="416"),
        _row(description="Перевод Иванову", amount="5000"),
    ]
    plan = StatementSqlPlan(
        operation="count",
        description_contains="операций",
        confidence=0.9,
    )
    grounded = refine_plan_with_rows(
        plan,
        question="сколько операций Yandex",
        rows=rows,
    )
    assert grounded.description_contains.lower() == "yandex"
    assert RowsDescriptionMatchProbe(rows).count(grounded.description_contains) == 2


def test_grounding_recovers_from_empty_after_noise_using_question_token_in_data():
    rows = [_row(description="Оплата в YANDEX*7372*OBLAKO Moskva RUS")]
    plan = StatementSqlPlan(operation="count", description_contains="", confidence=0.9)
    grounded = refine_plan_with_rows(
        plan,
        question="сколько операций Yandex",
        rows=rows,
    )
    assert grounded.description_contains.lower() == "yandex"


def test_grounding_does_not_invent_missing_counterparty():
    rows = [_row(description="Перевод Иванову")]
    plan = StatementSqlPlan(
        operation="count",
        description_contains="операций",
        confidence=0.9,
    )
    grounded = refine_plan_with_rows(
        plan,
        question="сколько операций Yandex",
        rows=rows,
    )
    # No Yandex in data → do not keep noise; leave empty rather than invent.
    assert grounded.description_contains == ""


@patch("app.services.chat.statement_sql_pipeline.refine_plan_with_db", side_effect=lambda db, **kw: kw["plan"])
@patch("app.services.chat.statement_sql_pipeline.synthesize_statement_sql_answer")
@patch("app.services.chat.statement_sql_pipeline.execute_statement_sql_plan")
@patch("app.services.chat.statement_sql_pipeline.plan_statement_sql")
def test_pipeline_runs_value_grounding_before_execute(
    mock_plan,
    mock_execute,
    mock_synthesize,
    mock_refine,
):
    from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
    from app.services.chat.statement_sql_facts import StatementSqlFacts
    from app.services.chat.statement_sql_models import StatementSqlPlanResult
    from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline
    from app.services.chat.statement_sql_synthesizer import StatementSqlSynthesisResult

    plan = StatementSqlPlan(
        operation="count",
        statement_file_id="stmt-1",
        description_contains="операций",
        confidence=0.9,
    )
    refined = plan.model_copy(update={"description_contains": "Yandex"})
    mock_refine.side_effect = lambda db, **kw: refined
    mock_plan.return_value = StatementSqlPlanResult(plan=plan, resolver="llm", reason="ok")
    mock_execute.return_value = StatementSqlExecutionResult(
        resolved=True,
        facts=StatementSqlFacts(
            operation="count",
            file_label="выписка.pdf",
            file_id="stmt-1",
            period_label="весь период",
            row_count=31,
            description_filter="Yandex",
        ),
    )
    mock_synthesize.return_value = StatementSqlSynthesisResult(
        text="Найдено 31 операция с Yandex.",
        via_llm=True,
    )

    result = run_statement_sql_pipeline(
        MagicMock(),
        case_id="case-1",
        question="сколько операций Yandex",
        scope_file_ids=["stmt-1"],
    )

    assert result is not None
    assert result["statement_sql_meta"]["row_count"] == 31
    assert result["statement_sql_meta"]["description_contains"] == "Yandex"
    mock_refine.assert_called_once()
    executed_plan = mock_execute.call_args.kwargs["plan"]
    assert executed_plan.description_contains == "Yandex"
