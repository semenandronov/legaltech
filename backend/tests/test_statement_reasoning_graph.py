"""Tests for plan → execute → critique reasoning graph."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_reasoning_graph import run_statement_reasoning_graph
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
)


def _row(*, row_id: str, desc: str, idx: int = 0) -> CaseFileTransaction:
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=idx,
        table_index=0,
        row_index=idx,
        operation_date=date(2026, 1, 10),
        operation_datetime_text="10.01.2026",
        amount_rub=Decimal("-1000"),
        amount_raw="-1000",
        description=desc,
        row_columns={},
        page_start=1,
        flow_direction="debit",
    )


@patch("app.services.chat.statement_reasoning_graph.create_legal_llm")
def test_reasoning_graph_counterparty_prefers_andropov(mock_llm):
    mock_llm.side_effect = RuntimeError("skip plan llm")

    rows = [
        _row(row_id="r1", desc="Перевод Андропову Андрею Викторовичу", idx=0),
        _row(row_id="r2", desc="Комиссия банка", idx=1),
    ]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="были ли операции с Андроповым Андреем Викторовичем?",
        rows=rows,
    )
    with bind_statement_table_session(session):
        final = run_statement_reasoning_graph(
            session,
            question=session.question,
        )

    assert final.get("status") == "accepted"
    log = " ".join(final.get("execution_log") or [])
    assert "Андропов" in log
    assert "counterparty_dossier" in session.tool_calls or "resolve_entity" in session.tool_calls


@patch("app.services.chat.statement_table_agent.create_legal_llm")
@patch("app.services.chat.statement_table_agent.reasoning_agent_enabled", return_value=True)
@patch("app.services.chat.statement_table_agent.run_statement_reasoning_graph")
def test_table_agent_uses_reasoning_path(mock_graph, _enabled, mock_llm):
    rows = [
        _row(row_id="r1", desc="Перевод Андропову А.В.", idx=0),
    ]

    def _fake_graph(session, *, question: str, progress=None):
        from app.services.chat.statement_lawyer_toolkit import (
            counterparty_dossier,
            resolve_entity,
        )

        resolve_entity.invoke({"hint": "Андропов", "question": question})
        counterparty_dossier.invoke({"token": "Андропов", "list_limit": "5"})
        return {
            "status": "accepted",
            "execution_log": ['{"grounded_token":"Андропов"}', '{"match_count":1}'],
            "reasoning_trace": ["plan", "critique: accepted"],
            "critique_issues": [],
            "revision_count": 0,
        }

    mock_graph.side_effect = _fake_graph
    synth = MagicMock()
    synth.invoke.return_value = MagicMock(content="Да, одна операция с Андроповым.")
    mock_llm.return_value = synth

    from app.services.chat.statement_table_agent import run_statement_table_agent

    db = MagicMock()
    result = run_statement_table_agent(
        db,
        case_id="case-1",
        question="операции с Андроповым?",
        file_id="stmt-1",
        file_label="выписка.pdf",
        rows=rows,
    )
    assert result is not None
    assert "Андропов" in result["response"]
    assert result["statement_sql_meta"]["resolver"] == "table_agent_reasoning"
