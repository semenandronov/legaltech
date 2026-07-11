from datetime import date
from decimal import Decimal

from app.models.case_file_transaction import CaseFileTransaction
from app.services.operations_chat_scope import filter_operations_scope


def _row(
    *,
    row_id: str,
    dt_text: str,
    amount: str,
    amount_rub: str,
    desc: str,
    counterparty: str = "",
) -> CaseFileTransaction:
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_date=date(2026, 5, 1),
        operation_datetime_text=dt_text,
        amount_rub=Decimal(amount_rub),
        amount_raw=amount,
        description=desc,
        row_columns={"Контрагент": counterparty} if counterparty else {},
        page_start=1,
    )


def test_scope_applies_row_search_and_numeric_filter():
    rows = [
        _row(
            row_id="r1",
            dt_text="01.05.2026 10:00",
            amount="-600 000,00",
            amount_rub="-600000.00",
            desc="Оплата ИП Иванов",
            counterparty="ИП Иванов",
        ),
        _row(
            row_id="r2",
            dt_text="02.05.2026 10:00",
            amount="-50 000,00",
            amount_rub="-50000.00",
            desc="Оплата ООО Ромашка",
            counterparty="ООО Ромашка",
        ),
    ]
    scope = filter_operations_scope(
        rows=rows,
        file_id="stmt-1",
        file_label="stmt.pdf",
        row_search="иванов",
        value_filters=[
            {
                "columnId": "op_amount",
                "operator": "number_less_than",
                "numberFrom": "-100000",
                "numberTo": None,
                "dateFrom": None,
                "dateTo": None,
                "textQuery": "",
                "selectedValues": [],
            }
        ],
    )

    assert scope.total_rows == 2
    assert len(scope.filtered_rows) == 1
    assert scope.filtered_rows[0].id == "r1"
    assert scope.has_active_scope_filters is True


def test_scope_applies_dynamic_column_equals_filter():
    rows = [
        _row(
            row_id="r1",
            dt_text="01.05.2026 10:00",
            amount="-100,00",
            amount_rub="-100.00",
            desc="Оплата ИП Иванов",
            counterparty="ИП Иванов",
        ),
        _row(
            row_id="r2",
            dt_text="02.05.2026 10:00",
            amount="-200,00",
            amount_rub="-200.00",
            desc="Оплата ООО Ромашка",
            counterparty="ООО Ромашка",
        ),
    ]
    scope = filter_operations_scope(
        rows=rows,
        file_id="stmt-1",
        file_label="stmt.pdf",
        value_filters=[
            {
                "columnId": "op_col_0",
                "operator": "equals",
                "selectedValues": ["ИП Иванов"],
                "textQuery": "",
                "dateFrom": None,
                "dateTo": None,
                "numberFrom": None,
                "numberTo": None,
            }
        ],
    )

    assert len(scope.filtered_rows) == 1
    assert scope.filtered_rows[0].id == "r1"
