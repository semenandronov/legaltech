"""Tests for statement Python sandbox."""
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.case_file_transaction import CaseFileTransaction
from app.services.chat.statement_python_sandbox import (
    run_python_in_sandbox,
    validate_user_code,
)
from app.services.chat.statement_scope_export import export_statement_scope_dataset

pytest.importorskip("pandas")


def _row(desc: str, amount: str = "1000", row_id: str = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee") -> CaseFileTransaction:
    return CaseFileTransaction(
        id=row_id,
        case_id="case-1",
        file_id="stmt-1",
        global_row_index=0,
        table_index=0,
        row_index=0,
        operation_datetime_text="14.05.2025 10:00",
        amount_rub=Decimal(amount),
        amount_raw=amount,
        description=desc,
        row_columns={},
        page_start=1,
    )


def test_validate_blocks_os_import():
    assert validate_user_code("import os\nprint(1)") is not None


def test_sandbox_groups_and_prints(tmp_path: Path):
    rows = [
        _row("ООО Вектор платеж 1", "98000", "11111111-1111-1111-1111-111111111111"),
        _row("ООО Вектор платеж 2", "98000", "22222222-2222-2222-2222-222222222222"),
        _row("ООО Вектор платеж 3", "98000", "33333333-3333-3333-3333-333333333333"),
    ]
    dataset = export_statement_scope_dataset(rows, file_label="t.pdf", parent_dir=tmp_path)
    code = """
matches = df[df["description"].str.contains("Вектор", case=False, na=False)]
print("count", len(matches))
print("sum", float(matches["amount_rub"].astype(float).sum()))
"""
    result = run_python_in_sandbox(
        code=code,
        csv_path=dataset.csv_path,
        work_dir=tmp_path / "run1",
    )
    assert result.ok, result.stderr
    assert "count 3" in result.stdout
    assert "sum 294000" in result.stdout.replace(".0", "")
