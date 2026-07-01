"""Tests for case chat transaction agent (delegates to file-scoped agent)."""

from unittest.mock import MagicMock, patch

from app.services.chat.case_transaction_agent import run_case_transaction_agent
from app.services.chat.file_scoped_agent import FileScopedAgentResult


@patch("app.services.chat.case_transaction_agent.run_statement_sql_pipeline", return_value=None)
@patch("app.services.chat.case_transaction_agent.run_file_scoped_agent")
@patch(
    "app.services.chat.case_transaction_agent.CaseFileTransactionService.list_transaction_file_ids",
    return_value=["f1"],
)
@patch("app.services.chat.case_transaction_agent.feature_enabled", return_value=True)
def test_chat_agent_resolves_via_react_sql_fallback(
    mock_feature,
    mock_list_ids,
    mock_run_agent,
    _mock_pipeline,
):
    mock_run_agent.return_value = FileScopedAgentResult(
        answer="11.06.2026 в 19:28: списание 3 100 ₽.",
        tools_called=True,
        sql_tools_called=True,
        search_tools_called=False,
        context_block="### list_case_transactions\n...",
        transaction_rows=[],
        rag_documents=[],
        messages=[],
    )

    db = MagicMock()
    result = run_case_transaction_agent(
        db,
        case_id="case-1",
        question="11.06.2026 19:28 как была операция?",
    )

    assert result is not None
    assert result["transaction_agent_resolved"] is True
    assert "19:28" in result["response"]
    mock_run_agent.assert_called_once()
    assert mock_run_agent.call_args.kwargs.get("sql_only") is True


@patch("app.services.chat.case_transaction_agent.feature_enabled", return_value=True)
@patch(
    "app.services.chat.case_transaction_agent.CaseFileTransactionService.list_transaction_file_ids",
    return_value=[],
)
def test_chat_agent_skips_without_statements(_mock_feature, _mock_list):
    db = MagicMock()
    result = run_case_transaction_agent(
        db,
        case_id="case-1",
        question="11.06.2026 19:28 как была операция?",
    )
    assert result is None
