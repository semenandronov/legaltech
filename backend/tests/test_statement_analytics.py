"""Unit tests for deterministic statement analytics (no DB, no LLM)."""

from datetime import date, timedelta
from decimal import Decimal

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_analytics import (
    AnomalyThresholds,
    classify_operation,
    compute_category_breakdown,
    compute_counterparty_profile,
    compute_monthly,
    compute_overview,
    detect_anomalies,
    detect_recurring_transfers,
    filter_by_date_range,
    format_amount_rub,
    parse_ru_date,
    suspicion_windows,
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
    # Fixtures pass an already-signed amount_rub; set flow so effective_amount
    # does not re-interpret an unsigned amount_raw as a card-statement debit.
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


def test_format_amount_rub():
    assert "₽" in format_amount_rub(Decimal("1234.5"))
    assert format_amount_rub(None) == "—"


def test_compute_overview_inflow_outflow_and_cash():
    rows = [
        _row(row_id="r1", amount="100000", desc="Поступление зарплата", idx=0),
        _row(row_id="r2", amount="-50000", desc="ООО Ромашка", idx=1),
        _row(row_id="r3", amount="-200000", desc="Снятие наличных в банкомате", idx=2),
        _row(row_id="r4", amount="-10000", desc="ООО Ромашка", idx=3),
    ]
    ov = compute_overview(rows, top_n=3)

    assert ov.operation_count == 4
    assert ov.flow.inflow_sum == Decimal("100000")
    assert ov.flow.outflow_sum == Decimal("260000")
    assert ov.flow.net_sum == Decimal("-160000")
    assert ov.cash_out_count == 1
    assert ov.cash_out_sum == Decimal("200000")
    assert ov.top_outflow_counterparties[0].description == "Снятие наличных в банкомате"
    assert ov.largest_operations[0].id == "r3"


def test_compute_monthly_buckets():
    rows = [
        _row(row_id="r1", amount="1000", desc="A", op_date=date(2026, 1, 5), idx=0),
        _row(row_id="r2", amount="-300", desc="B", op_date=date(2026, 1, 10), idx=1),
        _row(row_id="r3", amount="-500", desc="C", op_date=date(2026, 2, 1), idx=2),
    ]
    months = compute_monthly(rows)
    assert len(months) == 2
    assert months[0].label == "01.2026"
    assert months[0].inflow_sum == Decimal("1000")
    assert months[0].outflow_sum == Decimal("300")
    assert months[0].net_sum == Decimal("700")
    assert months[1].label == "02.2026"
    assert months[1].outflow_sum == Decimal("500")


def test_counterparty_profile_matches_token():
    rows = [
        _row(row_id="r1", amount="-100", desc="Оплата Yandex Plus", idx=0),
        _row(row_id="r2", amount="-200", desc="Yandex Cloud", idx=1),
        _row(row_id="r3", amount="-50", desc="VK Music", idx=2),
    ]
    profile = compute_counterparty_profile(rows, "Yandex")
    assert profile.matched is True
    assert profile.op_count == 2
    assert profile.outflow_sum == Decimal("300")

    empty = compute_counterparty_profile(rows, "Газпром")
    assert empty.matched is False
    assert empty.op_count == 0


def test_detect_structuring_same_counterparty_window():
    day = date(2026, 3, 1)
    rows = [
        _row(row_id="r1", amount="-10000", desc="Иванов И.И.", op_date=day, idx=0),
        _row(row_id="r2", amount="-12000", desc="Иванов И.И.", op_date=day + timedelta(days=1), idx=1),
        _row(row_id="r3", amount="-15000", desc="Иванов И.И.", op_date=day + timedelta(days=2), idx=2),
        _row(row_id="r4", amount="-500", desc="Магнит", op_date=day, idx=3),
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("1000000"),
            round_min=Decimal("1000000"),
            structuring_min_ops=3,
            structuring_window_days=3,
            spike_multiplier=100.0,
        ),
    )
    codes = {f.code for f in findings}
    assert "structuring" in codes
    structuring = next(f for f in findings if f.code == "structuring")
    assert structuring.severity == "high"
    assert any(r.description == "Иванов И.И." for r in structuring.rows)


def test_detect_large_cash_out():
    rows = [
        _row(row_id="r1", amount="-250000", desc="Выдача наличных", idx=0),
        _row(row_id="r2", amount="-500", desc="Магнит", idx=1),
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("100000"),
            round_min=Decimal("1000000"),
            structuring_min_ops=10,
            spike_multiplier=100.0,
        ),
    )
    assert any(f.code == "large_cash_out" for f in findings)


def test_detect_round_large_debit():
    rows = [
        _row(row_id="r1", amount="-100000", desc="Перевод ООО Вектор", idx=0),
        _row(row_id="r2", amount="-12345", desc="Магнит", idx=1),
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("1000000"),
            round_step=Decimal("10000"),
            round_min=Decimal("50000"),
            structuring_min_ops=10,
            spike_multiplier=100.0,
        ),
    )
    assert any(f.code == "round_large_debit" for f in findings)


def test_detect_outflow_spike():
    base = date(2026, 4, 1)
    rows = [
        _row(row_id="r1", amount="-1000", desc="A", op_date=base, idx=0),
        _row(row_id="r2", amount="-1000", desc="B", op_date=base + timedelta(days=1), idx=1),
        _row(row_id="r3", amount="-1000", desc="C", op_date=base + timedelta(days=2), idx=2),
        _row(
            row_id="r4",
            amount="-200000",
            desc="Крупный перевод",
            op_date=base + timedelta(days=3),
            idx=3,
        ),
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("50000"),
            round_min=Decimal("1000000"),
            structuring_min_ops=10,
            spike_multiplier=5.0,
        ),
    )
    assert any(f.code == "outflow_spike" for f in findings)


def test_detect_anomalies_empty_when_clean():
    rows = [
        _row(row_id="r1", amount="-120", desc="Магнит", idx=0),
        _row(row_id="r2", amount="-80", desc="Аптека", idx=1),
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("100000"),
            round_min=Decimal("50000"),
            structuring_min_ops=5,
            spike_multiplier=50.0,
            transit_min_amount=Decimal("1000000"),
            recurring_min_ops=50,
        ),
    )
    assert findings == []


def test_parse_ru_date_formats():
    assert parse_ru_date("10.03.2025") == date(2025, 3, 10)
    assert parse_ru_date("2025-03-10") == date(2025, 3, 10)
    assert parse_ru_date("10/03/2025") == date(2025, 3, 10)
    assert parse_ru_date("") is None
    assert parse_ru_date("чепуха") is None


def test_filter_by_date_range_inclusive_and_drops_undated():
    rows = [
        _row(row_id="r1", amount="-1", desc="A", op_date=date(2025, 1, 1), idx=0),
        _row(row_id="r2", amount="-1", desc="B", op_date=date(2025, 6, 1), idx=1),
        _row(row_id="r3", amount="-1", desc="C", op_date=date(2025, 12, 31), idx=2),
    ]
    scoped = filter_by_date_range(rows, date(2025, 3, 1), date(2025, 9, 1))
    assert [r.id for r in scoped] == ["r2"]
    # No bounds → returns all (including any undated).
    assert len(filter_by_date_range(rows, None, None)) == 3


def test_suspicion_windows_bases_and_bounds():
    windows = suspicion_windows(date(2025, 3, 10))
    codes = [c for c, *_ in windows]
    assert codes == ["preference_1m", "preference_6m", "unequal_1y", "harm_3y"]
    for _code, _label, d_from, d_to in windows:
        assert d_to == date(2025, 3, 10)
        assert d_from < d_to


def test_classify_operation_categories():
    assert classify_operation(_row(row_id="a", amount="-1", desc="Снятие наличных банкомат")) == "cash"
    assert classify_operation(_row(row_id="c", amount="-1", desc="Оплата НДФЛ")) == "tax"
    assert classify_operation(_row(row_id="d", amount="-1", desc="Аренда офиса")) == "utilities"
    assert classify_operation(_row(row_id="e", amount="1", desc="Зарплата за март")) == "salary"
    assert classify_operation(_row(row_id="g", amount="-1", desc="")) == "other"
    assert classify_operation(_row(row_id="m", amount="-1", desc="Магазин продукты")) == "card_spend"


def test_classify_loan_before_org_marker():
    # "Возврат займа ООО Вектор" — loan keyword wins over org handling.
    assert classify_operation(_row(row_id="l", amount="-1", desc="Возврат займа ООО Вектор")) == "loan"


def test_classify_individual_transfer_forms():
    # Surname + initials, initials + surname, full ФИО with patronymic, explicit markers.
    for desc in (
        "Перевод Иванов И.И.",
        "Иванову И. И.",
        "И.И. Иванов перевод",
        "Перевод Иванов Иван Иванович",
        "Перевод по СБП",
        "Перевод на карту",
    ):
        assert classify_operation(_row(row_id="i", amount="-1", desc=desc)) == "individual_transfer", desc


def test_classify_legal_entities_are_not_individuals():
    # Regression: IGNORECASE previously turned any 3 words into "individual_transfer".
    for desc in (
        "Перевод денежных средств",
        "Российские Железные Дороги",
        "ООО Ромашка оплата",
        "Публичное Акционерное Общество",
        "Оплата услуг компании Строй Групп",
    ):
        assert classify_operation(_row(row_id="o", amount="-1", desc=desc)) != "individual_transfer", desc


def test_compute_category_breakdown_sorted_by_turnover():
    rows = [
        _row(row_id="r1", amount="-200000", desc="Снятие наличных", idx=0),
        _row(row_id="r2", amount="-500", desc="Магазин продукты", idx=1),
        _row(row_id="r3", amount="-100000", desc="Возврат займа", idx=2),
    ]
    buckets = compute_category_breakdown(rows)
    codes = [b.category for b in buckets]
    assert "cash" in codes and "loan" in codes
    # Cash (200k) has the largest turnover → first.
    assert buckets[0].category == "cash"
    assert buckets[0].outflow_sum == Decimal("200000")


def test_detect_transit_pass_through():
    base = date(2025, 5, 1)
    rows = [
        _row(row_id="in", amount="500000", desc="Поступление от ООО Альфа", op_date=base, idx=0),
        _row(row_id="out1", amount="-300000", desc="Перевод ООО Бета", op_date=base, idx=1),
        _row(row_id="out2", amount="-180000", desc="Перевод ИП Гамма", op_date=base + timedelta(days=1), idx=2),
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("10000000"),
            round_min=Decimal("10000000"),
            structuring_min_ops=50,
            spike_multiplier=100.0,
            transit_min_amount=Decimal("100000"),
            transit_window_days=3,
            transit_ratio=0.8,
            recurring_min_ops=50,
        ),
    )
    assert any(f.code == "transit" for f in findings)


def test_transit_ignores_routine_small_spend():
    base = date(2025, 5, 1)
    rows = [
        _row(row_id="in", amount="500000", desc="Поступление от ООО Альфа", op_date=base, idx=0),
        # Many small routine debits summing to >80% of the inflow, but none is large.
        *[
            _row(row_id=f"s{i}", amount="-5000", desc="Магазин", op_date=base, idx=i + 1)
            for i in range(90)
        ],
    ]
    findings = detect_anomalies(
        rows,
        thresholds=AnomalyThresholds(
            large_amount=Decimal("100000"),
            round_min=Decimal("10000000"),
            structuring_min_ops=1000,
            spike_multiplier=100.0,
            transit_min_amount=Decimal("100000"),
            transit_window_days=3,
            transit_ratio=0.8,
            recurring_min_ops=1000,
        ),
    )
    assert not any(f.code == "transit" for f in findings)


def test_detect_recurring_transfers_across_months():
    rows = [
        _row(row_id="r1", amount="-15000", desc="Иванова М.П.", op_date=date(2025, 1, 5), idx=0),
        _row(row_id="r2", amount="-15000", desc="Иванова М.П.", op_date=date(2025, 2, 5), idx=1),
        _row(row_id="r3", amount="-15000", desc="Иванова М.П.", op_date=date(2025, 3, 5), idx=2),
        _row(row_id="r4", amount="-15000", desc="Иванова М.П.", op_date=date(2025, 4, 5), idx=3),
    ]
    recurring = detect_recurring_transfers(rows, min_ops=4)
    assert len(recurring) == 1
    assert recurring[0].op_count == 4
    assert recurring[0].total_sum == Decimal("60000")


def test_recurring_ignores_single_month_bunch():
    rows = [
        _row(row_id="r1", amount="-15000", desc="Петров", op_date=date(2025, 1, 5), idx=0),
        _row(row_id="r2", amount="-15000", desc="Петров", op_date=date(2025, 1, 6), idx=1),
        _row(row_id="r3", amount="-15000", desc="Петров", op_date=date(2025, 1, 7), idx=2),
        _row(row_id="r4", amount="-15000", desc="Петров", op_date=date(2025, 1, 8), idx=3),
    ]
    # All in one month → not "recurring over time" (that's structuring instead).
    assert detect_recurring_transfers(rows, min_ops=4) == []
