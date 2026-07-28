"""Export UI-scoped statement rows to a sandbox CSV (+ manifest)."""
from __future__ import annotations

import csv
import json
import logging
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, List, Sequence

from app.models.case_file_transaction import CaseFileTransaction

logger = logging.getLogger(__name__)

CANONICAL_COLUMNS: tuple[str, ...] = (
    "row_id",
    "operation_date",
    "operation_datetime_text",
    "amount_rub",
    "amount_raw",
    "flow_direction",
    "description",
    "verbatim_row_text",
)


@dataclass(frozen=True)
class StatementScopeDataset:
    work_dir: Path
    csv_path: Path
    manifest_path: Path
    row_count: int


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def export_statement_scope_dataset(
    rows: Sequence[CaseFileTransaction],
    *,
    file_label: str,
    scope_note: str = "",
    parent_dir: Path | None = None,
) -> StatementScopeDataset:
    base = parent_dir or Path(tempfile.mkdtemp(prefix="stmt_react_"))
    base.mkdir(parents=True, exist_ok=True)
    csv_path = base / "operations_scope.csv"
    manifest_path = base / "dataset_manifest.json"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CANONICAL_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "row_id": _cell(row.id),
                    "operation_date": _cell(row.operation_date),
                    "operation_datetime_text": _cell(row.operation_datetime_text),
                    "amount_rub": _cell(row.amount_rub),
                    "amount_raw": _cell(row.amount_raw),
                    "flow_direction": _cell(row.flow_direction),
                    "description": _cell(row.description),
                    "verbatim_row_text": _cell(row.verbatim_row_text),
                }
            )

    manifest = {
        "file_label": file_label,
        "scope_note": scope_note,
        "row_count": len(rows),
        "csv_filename": csv_path.name,
        "columns": [
            {
                "name": "row_id",
                "description": "UUID строки операции (для ссылок на первоисточник).",
            },
            {
                "name": "operation_date",
                "description": "Дата операции (ISO YYYY-MM-DD), если распознана.",
            },
            {
                "name": "operation_datetime_text",
                "description": "Дата/время как в выписке (текст).",
            },
            {
                "name": "amount_rub",
                "description": "Сумма в рублях; отрицательная — списание, положительная — поступление.",
            },
            {
                "name": "amount_raw",
                "description": "Сумма как в таблице выписки (текст).",
            },
            {
                "name": "flow_direction",
                "description": "debit | credit | пусто.",
            },
            {
                "name": "description",
                "description": "Назначение платежа / описание операции.",
            },
            {
                "name": "verbatim_row_text",
                "description": "Полная строка таблицы, если есть.",
            },
        ],
        "python_hint": (
            "import pandas as pd\n"
            f'df = pd.read_csv("{csv_path.name}")  # или используйте готовый df\n'
            "Контрагента извлекайте эвристикой из description (regex/contains)."
        ),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "[StatementScopeExport] rows=%s csv=%s",
        len(rows),
        csv_path,
    )
    return StatementScopeDataset(
        work_dir=base,
        csv_path=csv_path,
        manifest_path=manifest_path,
        row_count=len(rows),
    )


def read_manifest_text(manifest_path: Path) -> str:
    return manifest_path.read_text(encoding="utf-8")
