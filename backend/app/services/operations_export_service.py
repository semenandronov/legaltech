"""Export operations registry to CSV / Excel."""

from __future__ import annotations

import csv
import io
from typing import List, Sequence

from app.models.case_file_transaction import CaseFileTransaction
from app.schemas.operations import collect_column_headers
from app.services.table_schema_normalize import lookup_column_value


def _base_headers(*, single_file: bool, extra_headers: Sequence[str]) -> List[str]:
    if single_file and extra_headers:
        return ["№", "Дата", *list(extra_headers)]
    return ["№", "Дата", "Сумма", "Назначение", "Выписка"]


def _row_values(
    row: CaseFileTransaction,
    index: int,
    *,
    single_file: bool,
    extra_headers: Sequence[str],
) -> List[str]:
    columns = row.row_columns if isinstance(row.row_columns, dict) else {}
    date_text = row.operation_datetime_text or (
        row.operation_date.isoformat() if row.operation_date else ""
    )
    if single_file and extra_headers:
        values = [str(index), date_text]
        for header in extra_headers:
            values.append(lookup_column_value(columns, header))
        return values

    amount = row.amount_raw or (str(row.amount_rub) if row.amount_rub is not None else "")
    return [
        str(index),
        date_text,
        amount,
        row.description or "",
        row.source_filename or "",
    ]


def export_transactions_csv(
    rows: List[CaseFileTransaction],
    *,
    single_file: bool,
) -> bytes:
    extra_headers = collect_column_headers(rows, single_file=single_file)
    headers = _base_headers(single_file=single_file, extra_headers=extra_headers)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    for idx, row in enumerate(rows, start=1):
        writer.writerow(
            _row_values(row, idx, single_file=single_file, extra_headers=extra_headers)
        )
    return buffer.getvalue().encode("utf-8-sig")


def export_transactions_excel(
    rows: List[CaseFileTransaction],
    *,
    single_file: bool,
    sheet_name: str = "Операции",
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    extra_headers = collect_column_headers(rows, single_file=single_file)
    headers = _base_headers(single_file=single_file, extra_headers=extra_headers)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name[:31]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for idx, row in enumerate(rows, start=1):
        sheet.append(
            _row_values(row, idx, single_file=single_file, extra_headers=extra_headers)
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
