"""Tests for file-scoped SQL+RAG agent."""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.services.chat.file_scoped_agent import run_file_scoped_agent


@patch("app.services.chat.file_scoped_agent.create_react_agent")
@patch("app.services.chat.file_scoped_agent.create_legal_llm")
@patch("app.services.chat.file_scoped_agent.get_file_scoped_tools")
def test_file_scoped_agent_sql_and_search(mock_get_tools, mock_llm, mock_create_agent):
    mock_get_tools.return_value = [MagicMock(), MagicMock()]

    mock_create_agent.return_value.invoke.return_value = {
        "messages": [
            HumanMessage(content="Сумма списаний за 11.06.2026"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "aggregate_case_transactions", "args": {"on_date": "11.06.2026"}, "id": "1"},
                    {"name": "search_in_scoped_files", "args": {"query": "банк"}, "id": "2"},
                ],
            ),
            ToolMessage(content="Количество: 3", tool_call_id="1", name="aggregate_case_transactions"),
            ToolMessage(content="[1] Т-Банк", tool_call_id="2", name="search_in_scoped_files"),
            AIMessage(content="За 11.06.2026 списания на 3 100 ₽, банк Т-Банк."),
        ]
    }

    with patch(
        "app.services.chat.file_scoped_agent.pop_transaction_tool_citation_rows",
        return_value=[],
    ), patch(
        "app.services.chat.file_scoped_agent.pop_file_scoped_rag_documents",
        return_value=[],
    ):
        db = MagicMock()
        result = run_file_scoped_agent(
            db,
            case_id="c1",
            question="Сумма списаний за 11.06.2026",
            file_ids=["f1"],
            rag_service=MagicMock(),
            mode="tabular",
        )

    assert result is not None
    assert result.tools_called is True
    assert result.sql_tools_called is True
    assert result.search_tools_called is True
    assert "3 100" in result.answer or "списания" in result.answer.lower()


@patch("app.services.chat.file_scoped_agent.get_file_scoped_tools")
def test_file_scoped_agent_skips_without_tools(mock_get_tools):
    mock_get_tools.return_value = [MagicMock()]
    with patch("app.services.chat.file_scoped_agent.create_react_agent") as mock_agent:
        mock_agent.return_value.invoke.return_value = {
            "messages": [
                HumanMessage(content="привет"),
                AIMessage(content="Не могу помочь без инструментов."),
            ]
        }
        result = run_file_scoped_agent(
            MagicMock(),
            case_id="c1",
            question="привет",
            file_ids=["f1"],
            rag_service=MagicMock(),
        )
    assert result is None
