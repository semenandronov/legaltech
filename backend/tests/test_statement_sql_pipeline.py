"""Tests for statement SQL pipeline (plan → execute → synthesize)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.chat.statement_sql_executor import StatementSqlExecutionResult
from app.services.chat.statement_sql_facts import StatementSqlFacts
from app.services.chat.statement_sql_models import StatementSqlPlan, StatementSqlPlanResult
from app.services.chat.statement_sql_pipeline import run_statement_sql_pipeline
from app.services.chat.statement_sql_synthesizer import StatementSqlSynthesisResult


@patch("app.services.chat.statement_sql_pipeline.synthesize_statement_sql_answer")
@patch("app.services.chat.statement_sql_pipeline.execute_statement_sql_plan")
@patch("app.services.chat.statement_sql_pipeline.plan_statement_sql")
def test_pipeline_synthesizes_answer_from_sql_rows(
    mock_plan,
    mock_execute,
    mock_synthesize,
):
    plan = StatementSqlPlan(operation="count", statement_file_id="stmt-1", confidence=0.9)
    mock_plan.return_value = StatementSqlPlanResult(plan=plan, resolver="llm", reason="ok")
    mock_execute.return_value = StatementSqlExecutionResult(
        resolved=True,
        facts=StatementSqlFacts(
            operation="count",
            file_label="выписка.pdf",
            file_id="stmt-1",
            period_label="период 01.05.2026 — 31.05.2026",
            row_count=12,
        ),
    )
    mock_synthesize.return_value = StatementSqlSynthesisResult(
        text="По банковской выписке за май 2026 года — 12 операций.",
        via_llm=True,
    )

    db = MagicMock()
    result = run_statement_sql_pipeline(
        db,
        case_id="case-1",
        question="сколько операций в мае?",
        scope_file_ids=["stmt-1"],
    )

    assert result is not None
    assert result["transaction_agent_resolved"] is True
    assert "12 операций" in result["response"]
    assert result["statement_sql_meta"]["synthesized"] is True
    mock_synthesize.assert_called_once()
