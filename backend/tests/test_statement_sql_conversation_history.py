"""Tests for conversation history in statement SQL planner / synthesis path."""

from unittest.mock import MagicMock, patch

from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
from app.services.chat.statement_sql_facts import StatementSqlFacts
from app.services.chat.statement_sql_models import StatementSqlPlan, StatementSqlPlanResult
from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline
from app.services.chat.statement_sql_planner import (
    _build_planner_prompt,
    format_statement_sql_conversation_history,
)
from app.services.chat.statement_sql_synthesizer import (
    StatementSqlSynthesisResult,
    synthesize_statement_sql_answer,
)
from app.services.chat.structured_data_router import StatementFileCatalogEntry


def test_format_conversation_history_keeps_recent_turns():
    history = [
        {"role": "user", "content": "покажи списания Иванову"},
        {"role": "assistant", "content": "Нашёл 3 операции."},
        {"role": "user", "content": "а сумма?"},
        {"role": "assistant", "content": "1 200 000 ₽"},
    ]
    text = format_statement_sql_conversation_history(history, max_turns=2)
    assert "Пользователь: покажи списания Иванову" in text
    assert "Ассистент: Нашёл 3 операции." in text
    assert "а сумма?" in text


def test_planner_prompt_includes_conversation_history():
    prompt = _build_planner_prompt(
        question="а теперь только за март",
        catalog=[
            StatementFileCatalogEntry(
                file_id="stmt-1",
                filename="выписка.pdf",
                doc_type="bank_statement",
                has_sql_table=True,
            )
        ],
        scope_file_ids=["stmt-1"],
        conversation_history=[
            {"role": "user", "content": "покажи списания Иванову"},
            {"role": "assistant", "content": "Нашёл 3 операции."},
        ],
    )
    assert "Предыдущий диалог" in prompt
    assert "покажи списания Иванову" in prompt
    assert "а теперь только за март" in prompt
    assert "Самодостаточный новый вопрос" in prompt


def test_planner_prompt_excludes_prior_turn_state_and_hints():
    """Dialogue-only context: raw prior filters must not appear in the prompt."""
    prompt = _build_planner_prompt(
        question="сколько операций Yandex",
        catalog=[
            StatementFileCatalogEntry(
                file_id="stmt-1",
                filename="выписка.pdf",
                doc_type="bank_statement",
                has_sql_table=True,
            )
        ],
        scope_file_ids=["stmt-1"],
        prior_turn_state={
            "amount_compare": "gt",
            "amount_min": "9999",
            "operation": "list",
            "description_contains": "STALE",
        },
        sql_plan_hints={
            "date_from": "01.05.2026",
            "date_to": "31.05.2026",
            "amount_min": "9999",
        },
        conversation_history=[
            {"role": "user", "content": "найди операции больше 9999"},
            {"role": "assistant", "content": "Нашёл 10 операций."},
        ],
    )
    assert "сколько операций Yandex" in prompt
    assert "найди операции больше 9999" in prompt  # from dialogue text only
    assert "Prior turn" not in prompt
    assert "Структурные подсказки" not in prompt
    assert "Состояние прошлого" not in prompt
    assert "STALE" not in prompt
    assert "date_from': '01.05.2026'" not in prompt
    assert '"date_from": "01.05.2026"' not in prompt
    assert "'amount_min': '9999'" not in prompt
    assert '"amount_min": "9999"' not in prompt


@patch("app.services.chat.statement_sql_pipeline.synthesize_statement_sql_answer")
@patch("app.services.chat.statement_sql_pipeline.execute_statement_sql_plan")
@patch("app.services.chat.statement_sql_pipeline.plan_statement_sql")
def test_pipeline_forwards_conversation_history(mock_plan, mock_execute, mock_synthesize):
    plan = StatementSqlPlan(operation="sum", statement_file_id="stmt-1", confidence=0.9)
    mock_plan.return_value = StatementSqlPlanResult(plan=plan, resolver="llm", reason="ok")
    mock_execute.return_value = StatementSqlExecutionResult(
        resolved=True,
        facts=StatementSqlFacts(
            operation="sum",
            file_label="выписка.pdf",
            file_id="stmt-1",
            period_label="весь период выписки",
            row_count=3,
            amount_sum=None,
        ),
    )
    mock_synthesize.return_value = StatementSqlSynthesisResult(
        text="Сумма списаний Иванову — 1 200 000 ₽.",
        via_llm=True,
    )
    history = [
        {"role": "user", "content": "покажи списания Иванову"},
        {"role": "assistant", "content": "Нашёл 3 операции."},
    ]

    result = run_statement_sql_pipeline(
        MagicMock(),
        case_id="case-1",
        question="а сумма?",
        scope_file_ids=["stmt-1"],
        conversation_history=history,
    )

    assert result is not None
    assert mock_plan.call_args.kwargs.get("conversation_history") == history
    assert mock_synthesize.call_args.kwargs.get("conversation_history") == history


@patch("app.services.llm_factory.create_llm")
@patch("app.services.chat.statement_sql_synthesizer.statement_sql_synthesis_enabled", return_value=True)
def test_synthesis_includes_history_in_prompt(_mock_enabled, mock_create_llm):
    from langchain_core.messages import AIMessage

    llm = MagicMock()
    llm.invoke.return_value = AIMessage(content="Сумма — 1 200 000 ₽.")
    mock_create_llm.return_value = llm

    plan = StatementSqlPlan(operation="list", statement_file_id="stmt-1")
    execution = StatementSqlExecutionResult(
        resolved=True,
        facts=StatementSqlFacts(
            operation="list",
            file_label="выписка.pdf",
            file_id="stmt-1",
            period_label="весь период",
            row_count=3,
            sample_rows=[],
        ),
    )
    synthesize_statement_sql_answer(
        question="покажи подробнее",
        plan=plan,
        execution=execution,
        conversation_history=[
            {"role": "user", "content": "покажи списания Иванову"},
            {"role": "assistant", "content": "Нашёл 3 операции."},
        ],
    )

    human_msg = llm.invoke.call_args.args[0][1]
    content = human_msg.content if hasattr(human_msg, "content") else str(human_msg)
    assert "ПРЕДЫДУЩИЙ ДИАЛОГ" in content
    assert "покажи списания Иванову" in content
    assert "покажи подробнее" in content
    assert "НЕ источник чисел" in content
