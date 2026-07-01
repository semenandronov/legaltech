"""Tests for hybrid structured agent."""

from unittest.mock import MagicMock, patch

from app.services.chat.hybrid_structured_agent import run_hybrid_structured_agent


@patch("app.services.chat.hybrid_structured_agent._synthesize_hybrid_answer", return_value="Итоговый ответ")
@patch("app.services.chat.case_context_pipeline.complete_retrieval_after_recall")
@patch("app.services.chat.case_context_pipeline.run_hybrid_recall")
@patch("app.services.chat.hybrid_structured_agent.run_statement_sql_pipeline")
def test_hybrid_agent_combines_sql_and_rag(
    mock_sql,
    mock_recall,
    mock_complete,
    _mock_synth,
):
    mock_sql.return_value = {
        "response": "В мае 3 операции на 100 000 ₽",
        "citations": [{"label": "T1"}],
    }
    mock_recall.return_value = ([], {"recall_docs": 2})
    mock_complete.return_value = {
        "rag_context": "Возражение кредитора о ...",
        "citations": [{"label": "C1"}],
        "rag_documents": [],
    }

    patch = run_hybrid_structured_agent(
        MagicMock(),
        case_id="case-1",
        question="Сверь выписку с возражением",
        statement_scope_file_ids=["stmt-1"],
        rag_file_ids=["doc-2"],
    )

    assert patch is not None
    assert patch["hybrid_agent_resolved"] is True
    assert patch["response"] == "Итоговый ответ"
    assert len(patch["citations"]) == 2
    mock_sql.assert_called_once()
    mock_recall.assert_called_once()
