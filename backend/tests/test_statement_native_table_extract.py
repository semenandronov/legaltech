"""Unit tests for native multi-strategy statement table extraction."""

from __future__ import annotations

from app.services.statement_native_table_extract import (
    StatementNativeResult,
    StatementNativeRow,
    amount_header_preference,
    map_headers_to_roles,
    matrix_to_rows,
    project_row_by_roles,
    result_to_canonical_matrix,
    score_native_result,
)
from app.services.table_schema_normalize import ColumnRole


def test_amount_header_prefers_card_currency_over_op_currency():
    card = amount_header_preference("Сумма в валюте карты")
    op = amount_header_preference("Сумма в валюте операции")
    commission = amount_header_preference("Комиссия")
    assert card > op
    assert commission < 0


def test_map_headers_picks_single_best_amount():
    headers = [
        "Дата операции",
        "Описание операции",
        "Сумма в валюте операции",
        "Сумма в валюте карты",
        "Комиссия",
    ]
    roles = map_headers_to_roles(headers)
    amount_idxs = [i for i, r in enumerate(roles) if r == ColumnRole.AMOUNT]
    assert amount_idxs == [3]
    assert roles[0] == ColumnRole.DATE
    assert roles[1] == ColumnRole.DESCRIPTION


def test_matrix_to_rows_merges_continuation_lines():
    matrix = [
        ["Дата операции", "Описание", "Сумма"],
        ["01.02.2024", "Перевод", "-1 000,00"],
        ["12:30", "Ивану Иванову", ""],
        ["02.02.2024", "Покупка", "-50,00"],
    ]
    headers, roles, rows = matrix_to_rows(matrix)
    assert roles[2] == ColumnRole.AMOUNT
    assert len(rows) == 2
    assert "Ивану Иванову" in rows[0].description
    assert "12:30" in rows[0].date_text
    assert rows[1].amount_raw == "-50,00"
    assert len(rows[0].cells) == 3


def test_project_row_rejects_card_last4_as_amount():
    roles = [ColumnRole.DATE, ColumnRole.DESCRIPTION, ColumnRole.AMOUNT]
    assert (
        project_row_by_roles(["01.02.2024", "Shop", "1234"], roles) is None
    )


def test_score_penalizes_empty_descriptions():
    good = StatementNativeResult(
        strategy="t",
        rows=[
            StatementNativeRow("01.02.2024", "-100,00", "A"),
            StatementNativeRow("02.02.2024", "-200,00", "B"),
        ],
    )
    bad = StatementNativeResult(
        strategy="t",
        rows=[
            StatementNativeRow("01.02.2024", "-100,00", ""),
            StatementNativeRow("02.02.2024", "-200,00", ""),
        ]
        * 6,
    )
    assert score_native_result(good) > score_native_result(bad)


def test_result_to_canonical_matrix_keeps_all_original_columns():
    headers = [
        "Дата операции",
        "Описание операции",
        "Сумма в валюте операции",
        "Сумма в валюте карты",
        "Комиссия",
    ]
    roles = map_headers_to_roles(headers)
    cells = ("12.07.2025", "YANDEX*EDDA", "0.0 RUB", "-139.9", "0")
    result = StatementNativeResult(
        strategy="pymupdf_tables",
        headers=headers,
        column_roles=[r.value for r in roles],
        rows=[
            StatementNativeRow(
                date_text="12.07.2025",
                amount_raw="-139.9",
                description="YANDEX*EDDA",
                cells=cells,
            ),
        ],
        score=90.0,
    )
    out_headers, matrix, out_roles = result_to_canonical_matrix(result)
    assert out_headers == headers
    assert matrix[0] == list(cells)
    assert out_roles.count("amount") == 1
    assert out_headers[out_roles.index("amount")] == "Сумма в валюте карты"
    assert result.primary_amount_header == "Сумма в валюте карты"


def test_result_to_canonical_matrix_fallback_without_cells():
    result = StatementNativeResult(
        strategy="pymupdf_tables",
        rows=[
            StatementNativeRow("01.02.2024", "-139.9", "YANDEX", balance_raw="1000"),
        ],
        score=90.0,
    )
    headers, matrix, roles = result_to_canonical_matrix(result)
    assert headers[0] == "Дата операции"
    assert headers[2] == "Сумма"
    assert "Остаток" in headers
    assert matrix[0][2] == "-139.9"
    assert roles == ["date", "description", "amount", "balance"]


def test_vtb_style_preserves_secondary_money_cells():
    matrix = [
        [
            "Дата",
            "Описание операции",
            "Сумма в валюте",
            "Сумма в валюте",
            "Комиссия",
        ],
        [
            "операции",
            "",
            "операции",
            "карты",
            "",
        ],
        ["12.07.2025", "YANDEX*EDDA", "0.0 RUB", "-139.9", "0"],
        ["13.07.2025", "SHOP", "0.0 RUB", "-50.5", "0"],
    ]
    headers, roles, rows = matrix_to_rows(matrix)
    assert any("карт" in h.lower() for h in headers)
    assert roles.count(ColumnRole.AMOUNT) == 1
    amount_i = roles.index(ColumnRole.AMOUNT)
    assert "карт" in headers[amount_i].lower()
    assert len(rows) == 2
    assert rows[0].amount_raw == "-139.9"
    assert "YANDEX" in rows[0].description
    # Full PDF row preserved — op-currency and commission still present.
    assert "0.0 RUB" in rows[0].cells
    assert "-139.9" in rows[0].cells
    assert rows[0].cells[headers.index(next(h for h in headers if "комисс" in h.lower()))] == "0"

    result = StatementNativeResult(
        strategy="t",
        headers=headers,
        column_roles=[r.value for r in roles],
        rows=rows,
    )
    out_h, out_m, out_r = result_to_canonical_matrix(result)
    assert len(out_h) >= 5
    assert out_m[0][out_r.index("amount")] == "-139.9"
    assert "0.0 RUB" in out_m[0]
