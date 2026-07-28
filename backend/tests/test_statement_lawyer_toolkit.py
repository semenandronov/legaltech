"""Tests for the eight-tool lawyer statement toolkit."""

import json
from datetime import date
from decimal import Decimal

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_lawyer_tool_registry import STATEMENT_LAWYER_TOOL_NAMES
from app.services.chat.statement_lawyer_toolkit import (
    build_statement_lawyer_tools,
    flow_profile,
    resolve_entity,
)
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
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


def test_lawyer_toolkit_has_eight_tools():
    names = {t.name for t in build_statement_lawyer_tools()}
    assert names == set(STATEMENT_LAWYER_TOOL_NAMES)
    assert len(names) == 8


def test_resolve_entity_finds_surname_stem():
    rows = [_row("r1", "Перевод для А. Андропов А.В.", idx=0)]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="v.pdf",
        question="операции с Андроповым?",
        rows=rows,
    )
    with bind_statement_table_session(session):
        payload = json.loads(
            resolve_entity.invoke({"hint": "Андроповым", "question": session.question})
        )
    assert payload["ok"] is True
    assert payload["match_count"] >= 1


def test_flow_profile_combines_overview_and_monthly():
    rows = [
        _row("r1", "A", "-10000", idx=0),
        _row("r2", "B", "5000", idx=1),
    ]
    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="v.pdf",
        rows=rows,
    )
    with bind_statement_table_session(session):
        payload = json.loads(flow_profile.invoke({}))
    assert payload["ok"] is True
    assert "monthly" in payload
    assert payload["operation_count"] == 2
