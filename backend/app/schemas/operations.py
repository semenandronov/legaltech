"""Pydantic schemas for case operations (bank statement transactions) API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.case_file_transaction import CaseFileTransaction
from app.services.table_schema_normalize import (
    coalesce_header_union,
    normalize_stored_row_columns,
    project_row_columns_to_headers,
)


class OperationsAvailableFile(BaseModel):
    file_id: str
    filename: str
    transaction_count: int
    date_min: Optional[str] = None
    date_max: Optional[str] = None


class OperationsAvailableFilesResponse(BaseModel):
    files: List[OperationsAvailableFile]


class OperationsExportRequest(BaseModel):
    """Export the visible/filtered operation set (WYSIWYG)."""

    file_id: str = Field(..., min_length=1)
    format: Literal["excel", "csv"] = "excel"
    # When set, export exactly these rows in this order (current UI filter result).
    # When omitted/empty, export the full statement for file_id.
    transaction_ids: Optional[List[str]] = None


from app.services.transaction_source import resolve_row_source_for_db_row
from app.services.tabular_review_models import SourceReference


class OperationSourceReference(SourceReference):
    """CITATION_CONTRACT_V1 reference for a bank statement row."""


class OperationTransactionRow(BaseModel):
    id: str
    file_id: str
    source_filename: Optional[str] = None
    global_row_index: int
    operation_date: Optional[str] = None
    operation_datetime_text: Optional[str] = None
    amount_rub: Optional[float] = None
    amount_raw: Optional[str] = None
    description: Optional[str] = None
    row_columns: Dict[str, str] = Field(default_factory=dict)
    page_start: Optional[int] = None
    flow_direction: Optional[Literal["debit", "credit"]] = None
    verbatim_row_text: Optional[str] = None
    source_references: List[OperationSourceReference] = Field(default_factory=list)
    highlight_fragments: List[str] = Field(default_factory=list)


class OperationsSummary(BaseModel):
    total: int
    returned: int
    amount_sum_rub: float
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    file_count: int


class OperationsTransactionsResponse(BaseModel):
    transactions: List[OperationTransactionRow]
    summary: OperationsSummary
    column_headers: List[str] = Field(default_factory=list)


class OperationsChatRequest(BaseModel):
    question: str
    file_id: str = Field(..., min_length=1, description="ID оцифрованной выписки в деле")
    ui_state: "OperationsSessionUiState" = Field(default_factory=lambda: OperationsSessionUiState())


class OperationsChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    citations: Optional[List[Dict[str, str]]] = None


class OperationsChatHistoryResponse(BaseModel):
    messages: List[OperationsChatMessage]


class OperationsSessionUiState(BaseModel):
    value_filters: List[Dict[str, Any]] = Field(default_factory=list)
    row_search: str = ""
    petition_date: Optional[str] = None
    active_period: Optional[str] = None
    hide_operational_noise: bool = False
    view_mode: Literal["operations", "counterparties"] = "operations"
    basket_ids: List[str] = Field(default_factory=list)


class OperationsCounterpartyGroup(BaseModel):
    description: str
    op_count: int
    amount_sum_rub: float
    abs_amount_sum_rub: float


class OperationsCounterpartyGroupsResponse(BaseModel):
    groups: List[OperationsCounterpartyGroup] = Field(default_factory=list)
    returned: int
    total_groups: int


class OperationsPeriodInsight(BaseModel):
    period_id: str
    label: str
    date_from: str
    date_to: str
    count: int


class OperationsAnalysisInsightsResponse(BaseModel):
    petition_date: Optional[str] = None
    total_operations: int
    operational_noise_count: int
    filtered_count: int
    periods: List[OperationsPeriodInsight] = Field(default_factory=list)


class OperationsSessionResponse(BaseModel):
    file_id: str
    filename: Optional[str] = None
    ui_state: OperationsSessionUiState = Field(default_factory=OperationsSessionUiState)
    updated_at: Optional[str] = None


class OperationsSessionSummary(BaseModel):
    file_id: str
    filename: Optional[str] = None
    updated_at: Optional[str] = None
    transaction_count: Optional[int] = None
    date_min: Optional[str] = None
    date_max: Optional[str] = None


class OperationsSessionsListResponse(BaseModel):
    sessions: List[OperationsSessionSummary] = Field(default_factory=list)


class OperationsSessionSaveRequest(BaseModel):
    file_id: str = Field(..., min_length=1)
    filename: Optional[str] = None
    ui_state: OperationsSessionUiState = Field(default_factory=OperationsSessionUiState)


def _iso_date(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def serialize_transaction(
    row: CaseFileTransaction,
    *,
    column_headers: Optional[List[str]] = None,
) -> OperationTransactionRow:
    amount: Optional[float] = None
    if row.amount_rub is not None:
        amount = float(row.amount_rub)
    raw_columns = row.row_columns if isinstance(row.row_columns, dict) else {}
    columns = normalize_stored_row_columns(
        {str(k): str(v) for k, v in raw_columns.items() if k and v is not None}
    )
    if column_headers:
        columns = project_row_columns_to_headers(columns, column_headers)
    stored_refs = row.source_references if isinstance(row.source_references, list) else None
    verbatim, refs, fragments = resolve_row_source_for_db_row(
        row_columns=columns,
        verbatim_row_text=row.verbatim_row_text,
        source_references=stored_refs,
        page_start=row.page_start,
        char_start=row.char_start,
        char_end=row.char_end,
        description=row.description,
    )
    flow = row.flow_direction if row.flow_direction in ("debit", "credit") else None
    return OperationTransactionRow(
        id=str(row.id),
        file_id=str(row.file_id),
        source_filename=row.source_filename,
        global_row_index=int(row.global_row_index or 0),
        operation_date=_iso_date(row.operation_date),
        operation_datetime_text=row.operation_datetime_text,
        amount_rub=amount,
        amount_raw=row.amount_raw,
        description=row.description,
        row_columns=columns,
        page_start=row.page_start,
        flow_direction=flow,
        verbatim_row_text=verbatim or None,
        source_references=[
            OperationSourceReference(
                page=ref.get("page"),
                section=ref.get("section"),
                text=str(ref.get("text") or verbatim or ""),
                bbox=ref.get("bbox"),
                page_bbox=ref.get("page_bbox"),
            )
            for ref in refs
            if isinstance(ref, dict)
        ],
        highlight_fragments=fragments,
    )


def collect_column_headers(rows: List[CaseFileTransaction], *, single_file: bool) -> List[str]:
    if not single_file or not rows:
        return []
    headers: List[str] = []
    seen: set[str] = set()
    for row in rows:
        columns = row.row_columns if isinstance(row.row_columns, dict) else {}
        for key in columns:
            key_str = str(key).strip()
            if not key_str or key_str in seen:
                continue
            seen.add(key_str)
            headers.append(key_str)
    return coalesce_header_union(headers)


def build_summary(
    rows: List[CaseFileTransaction],
    *,
    total: int,
    file_id: str,
) -> OperationsSummary:
    amount_sum = Decimal("0")
    date_min = None
    date_max = None
    for row in rows:
        if row.amount_rub is not None:
            amount_sum += row.amount_rub
        if row.operation_date is not None:
            if date_min is None or row.operation_date < date_min:
                date_min = row.operation_date
            if date_max is None or row.operation_date > date_max:
                date_max = row.operation_date
    return OperationsSummary(
        total=total,
        returned=len(rows),
        amount_sum_rub=float(amount_sum),
        date_min=_iso_date(date_min),
        date_max=_iso_date(date_max),
        file_count=1,
    )
