"""Tests for statement analytical (insight) tools bound via the agent session."""

import json
from datetime import date, timedelta
from decimal import Decimal

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_insight_tools import (
    category_breakdown,
    counterparty_profile,
    detect_anomalies,
    monthly_breakdown,
    statement_overview,
    suspicion_period_analysis,
)
from app.services.chat.statement_table_session import (
    StatementTableSession,
    bind_statement_table_session,
)


def _row(
    *,
    row_id: str,
    amount: str,
    desc: str,
    op_date: date = date(2026, 5, 1),
    idx: int = 0,
) -> CaseFileTransaction:
    numeric = Decimal(amount.replace(" ", "").replace(",", "."))
    if numeric < 0:
        flow = "debit"
    elif numeric > 0:
        flow = "credit"
    else:
        flow = None
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=idx,
        table_index=0,
        row_index=idx,
        operation_date=op_date,
        operation_datetime_text=op_date.strftime("%d.%m.%Y"),
        amount_rub=numeric,
        amount_raw=amount,
        description=desc,
        row_columns={},
        page_start=1,
        flow_direction=flow,
    )


def _session(rows) -> StatementTableSession:
    return StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="анализ",
        rows=rows,
    )


def test_statement_overview_tool_reports_flows_and_citations():
    rows = [
        _row(row_id="r1", amount="100000", desc="Зарплата", idx=0),
        _row(row_id="r2", amount="-45000", desc="ООО Ромашка", idx=1),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(statement_overview.invoke({}))

    assert payload["ok"] is True
    assert payload["operation_count"] == 2
    assert payload["inflow_count"] == 1
    assert payload["outflow_count"] == 1
    assert "statement_overview" in session.tool_calls
    assert session.citation_rows  # largest ops registered for PDF linking
    assert session.analysis_findings


def test_monthly_breakdown_tool():
    rows = [
        _row(row_id="r1", amount="1000", desc="A", op_date=date(2026, 1, 5), idx=0),
        _row(row_id="r2", amount="-500", desc="B", op_date=date(2026, 2, 3), idx=1),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(monthly_breakdown.invoke({}))

    assert payload["ok"] is True
    assert len(payload["months"]) == 2
    assert payload["months"][0]["month"] == "01.2026"


def test_detect_anomalies_tool_flags_structuring():
    day = date(2026, 3, 1)
    rows = [
        _row(row_id="r1", amount="-10000", desc="Иванов", op_date=day, idx=0),
        _row(row_id="r2", amount="-11000", desc="Иванов", op_date=day + timedelta(days=1), idx=1),
        _row(row_id="r3", amount="-12000", desc="Иванов", op_date=day + timedelta(days=2), idx=2),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(detect_anomalies.invoke({}))

    assert payload["ok"] is True
    assert any(f["code"] == "structuring" for f in payload["findings"])
    assert session.citation_rows


def test_detect_anomalies_tool_clean_statement():
    rows = [
        _row(row_id="r1", amount="-120", desc="Магнит", idx=0),
        _row(row_id="r2", amount="-80", desc="Аптека", idx=1),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(detect_anomalies.invoke({}))

    assert payload["ok"] is True
    assert payload["findings"] == []


def test_counterparty_profile_tool():
    rows = [
        _row(row_id="r1", amount="-100", desc="Оплата Yandex Plus", idx=0),
        _row(row_id="r2", amount="-200", desc="Yandex Cloud", idx=1),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(counterparty_profile.invoke({"token": "Yandex"}))

    assert payload["ok"] is True
    assert payload["matched"] is True
    assert payload["op_count"] == 2


def test_counterparty_profile_tool_no_match():
    rows = [_row(row_id="r1", amount="-100", desc="Магнит", idx=0)]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(counterparty_profile.invoke({"token": "Газпром"}))

    assert payload["ok"] is True
    assert payload["matched"] is False


def test_counterparty_profile_tool_empty_token():
    rows = [_row(row_id="r1", amount="-100", desc="Магнит", idx=0)]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(counterparty_profile.invoke({"token": "  "}))

    assert payload["ok"] is False
    assert payload["reason"] == "empty_token"


def test_overview_tool_warns_on_truncated_scope(monkeypatch):
    # DB-backed statement larger than the analysis cap: only a subset is loaded.
    loaded = [
        _row(row_id="r1", amount="100000", desc="Зарплата", idx=0),
        _row(row_id="r2", amount="-45000", desc="ООО Ромашка", idx=1),
    ]

    class _Page:
        rows = loaded
        total = 25000

    monkeypatch.setattr(
        "app.services.chat.statement_table_session.CaseFileTransactionService.query_page",
        staticmethod(lambda *a, **k: _Page()),
    )

    session = StatementTableSession(
        case_id="case-1",
        file_id="stmt-1",
        file_label="выписка.pdf",
        question="что в выписке?",
        db=object(),  # truthy; query_page is mocked so it is never used
    )

    with bind_statement_table_session(session):
        payload = json.loads(statement_overview.invoke({}))

    assert payload["ok"] is True
    assert payload["truncated"] is True
    assert payload["total_row_count"] == 25000
    assert session.analyzed_row_count == 2
    assert "неполными" in payload["warning"]
    assert any("неполными" in f for f in session.analysis_findings)


def test_in_memory_scope_is_never_truncated():
    rows = [_row(row_id="r1", amount="-100", desc="Магнит", idx=0)]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(statement_overview.invoke({}))

    assert "truncated" not in payload
    assert session.rows_truncated is False
    assert session.total_row_count == 1
    assert session.analyzed_row_count == 1


def test_overview_tool_date_scoping():
    rows = [
        _row(row_id="r1", amount="-1000", desc="Старое", op_date=date(2024, 1, 1), idx=0),
        _row(row_id="r2", amount="-2000", desc="В окне", op_date=date(2025, 5, 1), idx=1),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(
            statement_overview.invoke({"date_from": "01.01.2025", "date_to": "31.12.2025"})
        )

    assert payload["ok"] is True
    assert payload["operation_count"] == 1
    assert "период 01.01.2025" in payload["period"]


def test_suspicion_period_analysis_tool():
    petition = date(2025, 3, 10)
    rows = [
        # Inside 1-month preference window: repayment to a creditor.
        _row(row_id="r1", amount="-300000", desc="Погашение кредита Банк", op_date=date(2025, 3, 1), idx=0),
        # Inside 1-year window: large transfer.
        _row(row_id="r2", amount="-500000", desc="Перевод ООО Ромашка", op_date=date(2024, 8, 1), idx=1),
        # Outside 3-year window.
        _row(row_id="r3", amount="-100000", desc="Старая операция", op_date=date(2020, 1, 1), idx=2),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(
            suspicion_period_analysis.invoke({"petition_date": "10.03.2025"})
        )

    assert payload["ok"] is True
    assert payload["petition_date"] == "10.03.2025"
    bases = [w["basis"] for w in payload["windows"]]
    assert bases == ["preference_1m", "preference_6m", "unequal_1y", "harm_3y"]
    one_month = next(w for w in payload["windows"] if w["basis"] == "preference_1m")
    assert one_month["operation_count"] == 1


def test_suspicion_period_analysis_bad_date():
    session = _session([_row(row_id="r1", amount="-100", desc="X", idx=0)])
    with bind_statement_table_session(session):
        payload = json.loads(suspicion_period_analysis.invoke({"petition_date": "чепуха"}))
    assert payload["ok"] is False
    assert payload["reason"] == "bad_petition_date"


def test_category_breakdown_tool():
    rows = [
        _row(row_id="r1", amount="-200000", desc="Снятие наличных банкомат", idx=0),
        _row(row_id="r2", amount="-100000", desc="Возврат займа", idx=1),
        _row(row_id="r3", amount="-500", desc="Оплата НДФЛ", idx=2),
    ]
    session = _session(rows)
    with bind_statement_table_session(session):
        payload = json.loads(category_breakdown.invoke({}))

    assert payload["ok"] is True
    codes = [c["category"] for c in payload["categories"]]
    assert "cash" in codes and "loan" in codes and "tax" in codes
    assert payload["categories"][0]["category"] == "cash"
    # Representative rows are surfaced and registered for PDF citations.
    assert payload["categories"][0]["examples"]
    assert session.citation_rows
