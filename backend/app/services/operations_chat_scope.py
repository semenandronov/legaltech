"""Utilities for operations chat scope based on the current table view."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import parse_operation_date, parse_amount_rub
from app.services.transaction_description_match import any_field_description_token_match

_EMPTY_VALUES = {"", "-", "—", "N/A"}
_NUMBER_RE = re.compile(r"[-+]?\s*[\d\s]+(?:[.,]\d+)?")


@dataclass(frozen=True)
class OperationsChatScope:
    file_id: str
    file_label: str
    total_rows: int
    filtered_rows: List[CaseFileTransaction]
    column_headers: List[str]
    row_search: str = ""
    active_filters: int = 0

    @property
    def has_active_scope_filters(self) -> bool:
        return bool(self.row_search.strip() or self.active_filters > 0)

    def scope_note(self) -> str:
        if not self.has_active_scope_filters:
            return "Ответ сформирован по текущей открытой выписке."
        return (
            "Ответ сформирован по текущему отфильтрованному виду таблицы: "
            f"после поиска и фильтров осталось {len(self.filtered_rows)} из {self.total_rows} операций."
        )


def collect_operations_column_headers(
    rows: Sequence[CaseFileTransaction],
) -> List[str]:
    seen: set[str] = set()
    headers: List[str] = []
    for row in rows:
        cols = row.row_columns if isinstance(row.row_columns, dict) else {}
        for key in cols.keys():
            header = str(key or "").strip()
            if header and header not in seen:
                seen.add(header)
                headers.append(header)
    return headers


def filter_operations_scope(
    *,
    rows: Sequence[CaseFileTransaction],
    file_id: str,
    file_label: str,
    row_search: str = "",
    value_filters: Sequence[Dict[str, Any]] | None = None,
) -> OperationsChatScope:
    column_headers = collect_operations_column_headers(rows)
    active_filters = [f for f in (value_filters or []) if _is_filter_condition_complete(f, column_headers)]

    filtered = list(rows)
    if active_filters:
        filtered = [row for row in filtered if all(_row_matches_filter(row, cond, column_headers) for cond in active_filters)]
    if row_search.strip():
        needle = row_search.strip().lower()
        filtered = [row for row in filtered if _row_matches_search(row, needle, column_headers)]

    return OperationsChatScope(
        file_id=file_id,
        file_label=file_label,
        total_rows=len(rows),
        filtered_rows=filtered,
        column_headers=column_headers,
        row_search=row_search,
        active_filters=len(active_filters),
    )


def _cell_map(row: CaseFileTransaction, column_headers: Sequence[str]) -> Dict[str, str]:
    row_columns = row.row_columns if isinstance(row.row_columns, dict) else {}
    cells: Dict[str, str] = {
        "op_date": str(row.operation_datetime_text or row.operation_date or ""),
        "op_amount": str(row.amount_raw or row.amount_rub or ""),
        "op_description": str(row.description or ""),
    }
    for index, header in enumerate(column_headers):
        cells[f"op_col_{index}"] = str(row_columns.get(header) or "")
    return cells


def _row_matches_search(
    row: CaseFileTransaction,
    needle: str,
    column_headers: Sequence[str],
) -> bool:
    if not needle:
        return True
    values = _cell_map(row, column_headers).values()
    return any(needle in str(value or "").lower() for value in values)


def _normalize_cell_value(value: Any) -> str:
    raw = str(value or "").strip()
    return "" if raw in _EMPTY_VALUES else raw


def _is_empty_cell_value(value: Any) -> bool:
    return _normalize_cell_value(value) == ""


def _parse_numeric_cell_value(value: Any) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw or raw in _EMPTY_VALUES:
        return None
    match = _NUMBER_RE.search(raw.replace("\u2212", "-"))
    if not match:
        return None
    try:
        return float(match.group(0).replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def _parse_filter_number(value: Any) -> Optional[float]:
    return _parse_numeric_cell_value(value)


def _parse_tabular_date(value: Any) -> Optional[date]:
    raw = str(value or "").strip()
    if not raw or raw in _EMPTY_VALUES:
        return None
    dot = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", raw)
    if dot:
        try:
            return date(int(dot.group(3)), int(dot.group(2)), int(dot.group(1)))
        except ValueError:
            return None
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    any_match = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", raw)
    if any_match:
        year_raw = any_match.group(3)
        year = 2000 + int(year_raw) if len(year_raw) == 2 else int(year_raw)
        try:
            return date(year, int(any_match.group(2)), int(any_match.group(1)))
        except ValueError:
            return None
    parsed = parse_operation_date(raw)
    if parsed is not None:
        return parsed
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _column_kind(column_id: str, column_headers: Sequence[str]) -> str:
    if column_id == "op_date":
        return "date"
    if column_id == "op_amount":
        return "number"
    if column_id.startswith("op_col_"):
        try:
            idx = int(column_id.removeprefix("op_col_"))
        except ValueError:
            return "text"
        header = column_headers[idx] if 0 <= idx < len(column_headers) else ""
        lowered = header.lower()
        if "дат" in lowered or "date" in lowered or "срок" in lowered:
            return "date"
        if re.search(r"(сумм|amount|дебет|кредит|баланс|колич|count|qty|числ)", lowered):
            return "number"
    return "text"


def _is_filter_condition_complete(cond: Dict[str, Any], column_headers: Sequence[str]) -> bool:
    column_id = str(cond.get("columnId") or "").strip()
    operator = str(cond.get("operator") or "").strip()
    if not column_id or not operator:
        return False

    kind = _column_kind(column_id, column_headers)
    selected_values = cond.get("selectedValues") if isinstance(cond.get("selectedValues"), list) else []
    text_query = str(cond.get("textQuery") or "").strip()
    date_from = str(cond.get("dateFrom") or "").strip()
    date_to = str(cond.get("dateTo") or "").strip()
    number_from = cond.get("numberFrom")
    number_to = cond.get("numberTo")

    if operator == "not_empty":
        return True
    if operator == "contains":
        return bool(text_query)
    if operator in {"equals", "not_equals"}:
        if kind == "date":
            return bool(date_from)
        if kind == "number":
            return _parse_filter_number(number_from) is not None
        return bool(selected_values)
    if operator in {"number_greater_than", "number_less_than"}:
        return _parse_filter_number(number_from) is not None
    if operator == "number_between":
        return _parse_filter_number(number_from) is not None and _parse_filter_number(number_to) is not None
    if operator in {"date_after", "date_before"}:
        return bool(date_from)
    if operator == "date_between":
        return bool(date_from and date_to)
    return False


def _row_matches_filter(
    row: CaseFileTransaction,
    cond: Dict[str, Any],
    column_headers: Sequence[str],
) -> bool:
    cells = _cell_map(row, column_headers)
    column_id = str(cond.get("columnId") or "").strip()
    operator = str(cond.get("operator") or "").strip()
    value = cells.get(column_id)
    kind = _column_kind(column_id, column_headers)

    normalized = _normalize_cell_value(value)
    if operator == "not_empty":
        return not _is_empty_cell_value(value)
    if operator == "contains":
        query = str(cond.get("textQuery") or "").strip().lower()
        return bool(normalized) and (not query or query in normalized.lower())

    if kind == "date":
        cell_date = _parse_tabular_date(value)
        filter_from = _parse_tabular_date(cond.get("dateFrom"))
        filter_to = _parse_tabular_date(cond.get("dateTo"))
        if operator == "equals":
            return cell_date is not None and filter_from is not None and cell_date == filter_from
        if operator == "not_equals":
            if filter_from is None or cell_date is None:
                return True
            return cell_date != filter_from
        if operator == "date_after":
            return cell_date is not None and filter_from is not None and cell_date > filter_from
        if operator == "date_before":
            return cell_date is not None and filter_from is not None and cell_date < filter_from
        if operator == "date_between":
            if cell_date is None or filter_from is None or filter_to is None:
                return False
            lo, hi = sorted((filter_from, filter_to))
            return lo <= cell_date <= hi

    if kind == "number":
        cell_num = _parse_numeric_cell_value(value)
        num_from = _parse_filter_number(cond.get("numberFrom"))
        num_to = _parse_filter_number(cond.get("numberTo"))
        if operator == "equals":
            return cell_num is not None and num_from is not None and cell_num == num_from
        if operator == "not_equals":
            if num_from is None or cell_num is None:
                return True
            return cell_num != num_from
        if operator == "number_greater_than":
            return cell_num is not None and num_from is not None and cell_num > num_from
        if operator == "number_less_than":
            return cell_num is not None and num_from is not None and cell_num < num_from
        if operator == "number_between":
            if cell_num is None or num_from is None or num_to is None:
                return False
            lo, hi = sorted((num_from, num_to))
            return lo <= cell_num <= hi

    selected_values = [
        _normalize_cell_value(item)
        for item in cond.get("selectedValues", [])
        if isinstance(item, (str, int, float))
    ]
    if operator == "equals":
        return normalized in selected_values
    if operator == "not_equals":
        return normalized not in selected_values
    return False


def apply_plan_filters_to_rows(
    rows: Sequence[CaseFileTransaction],
    *,
    on_date: Optional[date] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    description_contains: str = "",
    min_amount: Optional[Decimal] = None,
    max_amount: Optional[Decimal] = None,
) -> List[CaseFileTransaction]:
    needle = description_contains.strip()
    out: List[CaseFileTransaction] = []
    for row in rows:
        op_date = row.operation_date
        if on_date is not None and op_date != on_date:
            continue
        if date_from is not None and (op_date is None or op_date < date_from):
            continue
        if date_to is not None and (op_date is None or op_date > date_to):
            continue
        amount = row.amount_rub
        if min_amount is not None and (amount is None or amount < min_amount):
            continue
        if max_amount is not None and (amount is None or amount > max_amount):
            continue
        if needle:
            haystacks: Iterable[str] = (
                str(row.description or ""),
                str(row.operation_datetime_text or ""),
                str(row.amount_raw or ""),
                str(row.row_columns or ""),
            )
            if not any_field_description_token_match(haystacks, needle):
                continue
        out.append(row)
    return out
