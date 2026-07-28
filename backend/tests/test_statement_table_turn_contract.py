"""Turn contract: intent, validation, deterministic repair."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_table_session import StatementTableSession
from app.services.chat.statement_table_turn_contract import (
    assess_statement_turn_outcome,
    classify_statement_turn_intent,
    ground_counterparty_needle,
    repair_statement_turn,
)


def _row(row_id: str, desc: str, amount: str = "-1000", idx: int = 0) -> CaseFileTransaction:
    numeric = Decimal(amount.replace(" ", "").replace(",", "."))
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=idx,
        table_index=0,
        row_index=idx,
        operation_date=date(2026, 3, 1),
        operation_datetime_text="01.03.2026",
        amount_rub=numeric,
        amount_raw=amount,
        description=desc,
        row_columns={},
        page_start=1,
    )


def test_classify_counterparty_vs_top():
    assert classify_statement_turn_intent("были ли операции с Андроповым А.В.?") == "counterparty_lookup"
    assert classify_statement_turn_intent("выдели топ-5 контрагентов") == "factual_aggregate"
    assert classify_statement_turn_intent("что подозрительного в выписке?") == "open_analytics"


def test_ground_counterparty_needle_fio():
    rows = [
        _row("r1", "Перевод для А. Андропов А.В. Операция по карте", idx=0),
        _row("r2", "Прочее", idx=1),
    ]
    needle = ground_counterparty_needle(
        "были ли операции с Андроповым А.В.?",
        rows=rows,
    )
    assert needle
    assert "Андропов" in needle


def test_assess_flags_overview_on_counterparty_question():
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="были ли операции с Андроповым А.В.?",
        rows=[
            _row("r1", "Перевод для А. Андропов А.В.", idx=0),
        ],
    )
    session.tool_calls = ["flow_profile"]
    outcome = assess_statement_turn_outcome(
        question=session.question,
        session=session,
    )
    assert outcome.intent == "counterparty_lookup"
    assert outcome.needs_deterministic_repair is True
    assert outcome.accept_insight_path is False


def test_repair_counterparty_after_wrong_overview():
    rows = [
        _row("r1", "Перевод для А. Андропов А.В.", "-5000", idx=0),
        _row("r2", "Прочее", "-100", idx=1),
    ]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="были ли операции с Андроповым А.В.?",
        rows=rows,
    )
    session.tool_calls = ["flow_profile"]
    outcome = assess_statement_turn_outcome(question=session.question, session=session)
    db = MagicMock()
    patch_result = repair_statement_turn(
        db=db,
        case_id="case-1",
        session=session,
        question=session.question,
        outcome=outcome,
    )
    assert patch_result is not None
    assert patch_result["statement_sql_meta"]["resolver"] == "table_agent_repair"
    assert "Андропов" in patch_result["response"]
    assert "Да," in patch_result["response"] or "1 операц" in patch_result["response"]


@patch("app.services.chat.statement_table_agent.reasoning_agent_enabled", return_value=False)
@patch("app.services.chat.statement_table_agent.create_agent")
def test_table_agent_defers_counterparty_to_resolver(mock_create_agent, mock_reasoning_off):
    from app.services.chat.statement_table_agent import run_statement_table_agent

    rows = [
        _row("r1", "Перевод для А. Андропов А.В.", "-5000", idx=0),
    ]

    result = run_statement_table_agent(
        MagicMock(),
        case_id="case-1",
        question="были ли операции с Андроповым А.В.?",
        file_id="stmt-1",
        file_label="выписка.pdf",
        rows=rows,
    )

    assert result is None
    mock_create_agent.return_value.invoke.assert_not_called()
