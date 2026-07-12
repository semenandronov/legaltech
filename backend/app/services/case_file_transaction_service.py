"""Ingest and query structured-table rows (bank statements) for case assistant."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Literal, Optional, Sequence

from langchain_core.documents import Document
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session

from app.config import config
from app.models.case import File as FileModel
from app.models.case_file_transaction import CaseFileTransaction
from app.services.structured_table_indexer import is_structured_table_document
from app.services.transaction_description_match import (
    description_token_match,
    sql_transaction_description_token_match,
)
from app.services.transaction_source import extract_row_source_from_document

logger = logging.getLogger(__name__)

AbsoluteAmountCompare = Literal["none", "gt", "gte", "lt", "lte", "between"]
TransactionOrderBy = Literal["date_asc", "abs_amount_desc"]
DescriptionGroupOrderBy = Literal["abs_sum_desc", "count_desc"]

_DATE_HEADER_RE = re.compile(
    r"(дата|date)",
    re.IGNORECASE,
)
_AMOUNT_HEADER_RE = re.compile(
    r"(сумм|amount|дебет|кредит)",
    re.IGNORECASE,
)
_DEBIT_HEADER_RE = re.compile(
    r"(дебет|debit)",
    re.IGNORECASE,
)
_CREDIT_HEADER_RE = re.compile(
    r"(кредит|credit)",
    re.IGNORECASE,
)
_DESCRIPTION_HEADER_RE = re.compile(
    r"(описан|назначен|description|purpose|контрагент|получател)",
    re.IGNORECASE,
)
_DATE_DDMMYYYY_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
_AMOUNT_NUM_RE = re.compile(r"[-+]?\s*[\d\s]+(?:[.,]\d{2})?")


@dataclass(frozen=True)
class ParsedTransactionRow:
    global_row_index: int
    table_index: int
    row_index: int
    operation_date: Optional[date]
    operation_datetime_text: Optional[str]
    amount_rub: Optional[Decimal]
    amount_raw: Optional[str]
    description: Optional[str]
    row_columns: Dict[str, str]
    page_start: Optional[int]
    char_start: Optional[int]
    char_end: Optional[int]
    verbatim_row_text: Optional[str] = None
    source_references: Optional[List[Dict[str, Any]]] = None
    flow_direction: Optional[str] = None


def feature_enabled() -> bool:
    return bool(getattr(config, "CASE_FILE_TRANSACTIONS_ENABLED", False))


def _pick_column(columns: Dict[str, str], pattern: re.Pattern[str]) -> Optional[str]:
    for key in columns:
        if pattern.search(key or ""):
            return key
    return None


def _pick_debit_credit_columns(columns: Dict[str, str]) -> tuple[Optional[str], Optional[str]]:
    debit_key: Optional[str] = None
    credit_key: Optional[str] = None
    for key in columns:
        label = key or ""
        if _CREDIT_HEADER_RE.search(label) and not _DEBIT_HEADER_RE.search(label):
            credit_key = key
        elif _DEBIT_HEADER_RE.search(label):
            debit_key = key
    return debit_key, credit_key


def _cell_has_amount(value: str) -> bool:
    raw = (value or "").strip()
    if not raw or raw in {"—", "-", "0", "0,00", "0.00"}:
        return False
    amount, _ = parse_amount_rub(raw)
    return amount is not None and amount != 0


def _resolve_amount_and_flow(
    normalized: Dict[str, str],
) -> tuple[Optional[Decimal], Optional[str], Optional[str], Optional[str]]:
    """Returns amount_rub, amount_raw, flow_direction (debit|credit)."""
    debit_key, credit_key = _pick_debit_credit_columns(normalized)
    debit_val = normalized.get(debit_key, "") if debit_key else ""
    credit_val = normalized.get(credit_key, "") if credit_key else ""

    if debit_key and _cell_has_amount(debit_val):
        amount_rub, amount_raw = parse_amount_rub(debit_val)
        return amount_rub, amount_raw, "debit", debit_key
    if credit_key and _cell_has_amount(credit_val):
        amount_rub, amount_raw = parse_amount_rub(credit_val)
        return amount_rub, amount_raw, "credit", credit_key

    amount_key = _pick_column(normalized, _AMOUNT_HEADER_RE)
    amount_raw = normalized.get(amount_key, "") if amount_key else None
    amount_rub, amount_raw_out = parse_amount_rub(amount_raw or "")
    return amount_rub, amount_raw_out or None, None, amount_key


def parse_operation_date(value: str) -> Optional[date]:
    text = (value or "").strip()
    if not text:
        return None
    match = _DATE_DDMMYYYY_RE.search(text)
    if not match:
        return None
    day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_amount_rub(value: str) -> tuple[Optional[Decimal], str]:
    raw = (value or "").strip()
    if not raw:
        return None, raw
    match = _AMOUNT_NUM_RE.search(raw.replace("\u2212", "-"))
    if not match:
        return None, raw
    num_text = match.group(0).replace(" ", "").replace(",", ".")
    try:
        amount = Decimal(num_text)
        return amount, raw
    except InvalidOperation:
        return None, raw


def parse_row_from_metadata(metadata: Dict[str, Any]) -> Optional[ParsedTransactionRow]:
    row_columns = metadata.get("row_columns")
    if not isinstance(row_columns, dict) or not row_columns:
        return None

    normalized = {str(k): str(v) for k, v in row_columns.items() if k and v is not None}
    if not normalized:
        return None

    date_key = _pick_column(normalized, _DATE_HEADER_RE)
    desc_key = _pick_column(normalized, _DESCRIPTION_HEADER_RE)

    datetime_text = normalized.get(date_key, "") if date_key else None
    op_date = parse_operation_date(datetime_text or "")

    amount_rub, amount_raw, flow_direction, _amount_key = _resolve_amount_and_flow(normalized)

    description = normalized.get(desc_key, "") if desc_key else None
    if not description:
        for key, val in normalized.items():
            if _DESCRIPTION_HEADER_RE.search(key):
                description = val
                break

    return ParsedTransactionRow(
        global_row_index=int(metadata.get("global_row_index") or 0),
        table_index=int(metadata.get("table_index") or 0),
        row_index=int(metadata.get("row_index") or 0),
        operation_date=op_date,
        operation_datetime_text=datetime_text,
        amount_rub=amount_rub,
        amount_raw=amount_raw,
        description=(description or "").strip() or None,
        row_columns=normalized,
        page_start=int(metadata["page_start"]) if metadata.get("page_start") is not None else None,
        char_start=int(metadata["char_start"]) if metadata.get("char_start") is not None else None,
        char_end=int(metadata["char_end"]) if metadata.get("char_end") is not None else None,
        flow_direction=flow_direction,
    )


def parse_row_from_document(doc: Document) -> Optional[ParsedTransactionRow]:
    md = doc.metadata or {}
    if md.get("chunk_level") != "row":
        return None
    row = parse_row_from_metadata(md)
    if not row:
        return None
    verbatim, refs = extract_row_source_from_document(doc)
    return ParsedTransactionRow(
        global_row_index=row.global_row_index,
        table_index=row.table_index,
        row_index=row.row_index,
        operation_date=row.operation_date,
        operation_datetime_text=row.operation_datetime_text,
        amount_rub=row.amount_rub,
        amount_raw=row.amount_raw,
        description=row.description,
        row_columns=row.row_columns,
        page_start=row.page_start,
        char_start=row.char_start,
        char_end=row.char_end,
        verbatim_row_text=verbatim or None,
        source_references=refs or None,
        flow_direction=row.flow_direction,
    )


def rows_from_documents(documents: Sequence[Document]) -> List[ParsedTransactionRow]:
    parsed: List[ParsedTransactionRow] = []
    for doc in documents:
        row = parse_row_from_document(doc)
        if row:
            parsed.append(row)
    parsed.sort(key=lambda r: r.global_row_index)
    return parsed


def filter_parsed_rows(
    rows: Sequence[ParsedTransactionRow],
    *,
    on_date: Optional[date] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    description_contains: Optional[str] = None,
    min_amount: Optional[Decimal] = None,
    max_amount: Optional[Decimal] = None,
    limit: int = 200,
) -> List[ParsedTransactionRow]:
    result: List[ParsedTransactionRow] = []
    needle = (description_contains or "").strip()

    for row in rows:
        if on_date is not None and row.operation_date != on_date:
            continue
        if date_from is not None and (row.operation_date is None or row.operation_date < date_from):
            continue
        if date_to is not None and (row.operation_date is None or row.operation_date > date_to):
            continue
        if needle:
            hay = " ".join(
                filter(
                    None,
                    [
                        row.description or "",
                        row.operation_datetime_text or "",
                        " ".join(row.row_columns.values()),
                    ],
                )
            )
            if not description_token_match(hay, needle):
                continue
        if min_amount is not None and (row.amount_rub is None or row.amount_rub < min_amount):
            continue
        if max_amount is not None and (row.amount_rub is None or row.amount_rub > max_amount):
            continue
        result.append(row)
        if len(result) >= limit:
            break
    return result


def format_db_row_for_agent(row: CaseFileTransaction, *, file_label: str = "") -> str:
    parts = [
        f"#{int(row.global_row_index) + 1}",
        f"дата: {row.operation_datetime_text or row.operation_date or '—'}",
        f"сумма: {row.amount_raw or row.amount_rub or '—'}",
        f"описание: {row.description or '—'}",
    ]
    if file_label:
        parts.insert(0, f"файл: {file_label}")
    if row.page_start:
        parts.append(f"стр. PDF: {row.page_start}")
    return " | ".join(parts)


def format_row_for_agent(row: ParsedTransactionRow, *, file_label: str = "") -> str:
    parts = [
        f"#{row.global_row_index + 1}",
        f"дата: {row.operation_datetime_text or row.operation_date or '—'}",
        f"сумма: {row.amount_raw or row.amount_rub or '—'}",
        f"описание: {row.description or '—'}",
    ]
    if file_label:
        parts.insert(0, f"файл: {file_label}")
    if row.page_start:
        parts.append(f"стр. PDF: {row.page_start}")
    return " | ".join(parts)


@dataclass(frozen=True)
class TransactionFileSummary:
    file_id: str
    filename: str
    transaction_count: int
    date_min: Optional[date]
    date_max: Optional[date]


@dataclass(frozen=True)
class TransactionQueryPage:
    rows: List[CaseFileTransaction]
    total: int


@dataclass(frozen=True)
class TransactionAggregateTotals:
    count: int
    amount_sum: Decimal


@dataclass(frozen=True)
class TransactionDescriptionGroup:
    description: str
    op_count: int
    amount_sum: Decimal
    abs_amount_sum: Decimal


def _order_clause(order_by: TransactionOrderBy):
    if order_by == "abs_amount_desc":
        return (
            func.abs(CaseFileTransaction.amount_rub).desc().nullslast(),
            CaseFileTransaction.operation_date.asc().nullslast(),
            CaseFileTransaction.global_row_index.asc(),
        )
    return (
        CaseFileTransaction.operation_date.asc().nullslast(),
        CaseFileTransaction.global_row_index.asc(),
    )


class CaseFileTransactionService:
    """Persist and query transaction rows for structured-table files."""

    @staticmethod
    def case_has_transactions(
        db: Session,
        case_id: str,
        file_ids: Optional[Sequence[str]] = None,
    ) -> bool:
        if not feature_enabled():
            return False
        q = db.query(CaseFileTransaction.id).filter(CaseFileTransaction.case_id == case_id)
        if file_ids:
            q = q.filter(CaseFileTransaction.file_id.in_(list(file_ids)))
        return q.limit(1).first() is not None

    @staticmethod
    def list_transaction_file_ids(db: Session, case_id: str) -> List[str]:
        rows = (
            db.query(CaseFileTransaction.file_id)
            .filter(CaseFileTransaction.case_id == case_id)
            .distinct()
            .all()
        )
        return [r[0] for r in rows if r[0]]

    @staticmethod
    def sync_from_documents(
        db: Session,
        *,
        case_id: str,
        file_id: str,
        filename: str,
        documents: Sequence[Document],
    ) -> int:
        if not feature_enabled():
            return 0
        if not is_structured_table_document(documents):
            CaseFileTransactionService.delete_for_file(db, file_id)
            return 0

        parsed_rows = rows_from_documents(documents)
        if not parsed_rows:
            CaseFileTransactionService.delete_for_file(db, file_id)
            return 0

        CaseFileTransactionService.delete_for_file(db, file_id)

        models: List[CaseFileTransaction] = []
        for row in parsed_rows:
            models.append(
                CaseFileTransaction(
                    id=str(uuid.uuid4()),
                    case_id=case_id,
                    file_id=file_id,
                    global_row_index=row.global_row_index,
                    table_index=row.table_index,
                    row_index=row.row_index,
                    operation_date=row.operation_date,
                    operation_datetime_text=row.operation_datetime_text,
                    amount_rub=row.amount_rub,
                    amount_raw=row.amount_raw,
                    description=row.description,
                    row_columns=row.row_columns,
                    page_start=row.page_start,
                    char_start=row.char_start,
                    char_end=row.char_end,
                    verbatim_row_text=row.verbatim_row_text,
                    source_references=row.source_references,
                    flow_direction=row.flow_direction,
                    source_filename=filename,
                )
            )

        db.bulk_save_objects(models)
        db.commit()
        logger.info(
            "[CaseFileTransactions] synced %s rows for file=%s case=%s",
            len(models),
            file_id,
            case_id,
        )
        return len(models)

    @staticmethod
    def delete_for_file(db: Session, file_id: str) -> None:
        db.query(CaseFileTransaction).filter(CaseFileTransaction.file_id == file_id).delete(
            synchronize_session=False
        )
        db.commit()

    @staticmethod
    def _apply_query_filters(
        q,
        *,
        case_id: str,
        file_id: Optional[str] = None,
        file_ids: Optional[Sequence[str]] = None,
        on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        description_contains: Optional[str] = None,
        search: Optional[str] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        abs_amount_compare: AbsoluteAmountCompare = "none",
        abs_amount_min: Optional[Decimal] = None,
        abs_amount_max: Optional[Decimal] = None,
        flow: Optional[str] = None,
    ):
        q = q.filter(CaseFileTransaction.case_id == case_id)

        scope_ids = list(file_ids or [])
        if file_id:
            scope_ids = [file_id]
        if scope_ids:
            q = q.filter(CaseFileTransaction.file_id.in_(scope_ids))

        if on_date is not None:
            q = q.filter(CaseFileTransaction.operation_date == on_date)
        if date_from is not None:
            q = q.filter(CaseFileTransaction.operation_date >= date_from)
        if date_to is not None:
            q = q.filter(CaseFileTransaction.operation_date <= date_to)

        # Entity filter (chat/SQL plan): whole-token match, not substring.
        # Free-text UI search: keep substring ILIKE for partial typing.
        desc_needle = (description_contains or "").strip()
        search_needle = (search or "").strip()
        if desc_needle:
            q = q.filter(
                sql_transaction_description_token_match(
                    description_col=CaseFileTransaction.description,
                    row_columns_col=CaseFileTransaction.row_columns,
                    datetime_text_col=CaseFileTransaction.operation_datetime_text,
                    amount_raw_col=CaseFileTransaction.amount_raw,
                    needle=desc_needle,
                )
            )
        elif search_needle:
            needle = f"%{search_needle}%"
            q = q.filter(
                or_(
                    CaseFileTransaction.description.ilike(needle),
                    cast(CaseFileTransaction.row_columns, String).ilike(needle),
                    CaseFileTransaction.operation_datetime_text.ilike(needle),
                    CaseFileTransaction.amount_raw.ilike(needle),
                )
            )
        if min_amount is not None:
            q = q.filter(CaseFileTransaction.amount_rub >= min_amount)
        if max_amount is not None:
            q = q.filter(CaseFileTransaction.amount_rub <= max_amount)
        amount_abs = func.abs(CaseFileTransaction.amount_rub)
        if abs_amount_compare == "gt" and abs_amount_min is not None:
            q = q.filter(amount_abs > abs_amount_min)
        elif abs_amount_compare == "gte" and abs_amount_min is not None:
            q = q.filter(amount_abs >= abs_amount_min)
        elif abs_amount_compare == "lt" and abs_amount_max is not None:
            q = q.filter(amount_abs < abs_amount_max)
        elif abs_amount_compare == "lte" and abs_amount_max is not None:
            q = q.filter(amount_abs <= abs_amount_max)
        elif (
            abs_amount_compare == "between"
            and abs_amount_min is not None
            and abs_amount_max is not None
        ):
            q = q.filter(amount_abs >= abs_amount_min, amount_abs <= abs_amount_max)
        if flow in ("debit", "credit"):
            q = q.filter(CaseFileTransaction.flow_direction == flow)
        return q

    @staticmethod
    def list_available_files(db: Session, case_id: str) -> List[TransactionFileSummary]:
        if not feature_enabled():
            return []

        grouped = (
            db.query(
                CaseFileTransaction.file_id,
                func.count(CaseFileTransaction.id).label("tx_count"),
                func.min(CaseFileTransaction.operation_date).label("date_min"),
                func.max(CaseFileTransaction.operation_date).label("date_max"),
                func.max(CaseFileTransaction.source_filename).label("source_filename"),
            )
            .filter(CaseFileTransaction.case_id == case_id)
            .group_by(CaseFileTransaction.file_id)
            .order_by(func.max(CaseFileTransaction.source_filename).asc())
            .all()
        )
        if not grouped:
            return []

        file_ids = [row.file_id for row in grouped if row.file_id]
        file_rows = (
            db.query(FileModel.id, FileModel.filename)
            .filter(FileModel.case_id == case_id, FileModel.id.in_(file_ids))
            .all()
        )
        filename_by_id = {fid: name for fid, name in file_rows}

        summaries: List[TransactionFileSummary] = []
        for row in grouped:
            if not row.file_id:
                continue
            summaries.append(
                TransactionFileSummary(
                    file_id=row.file_id,
                    filename=filename_by_id.get(row.file_id) or row.source_filename or row.file_id,
                    transaction_count=int(row.tx_count or 0),
                    date_min=row.date_min,
                    date_max=row.date_max,
                )
            )
        return summaries

    @staticmethod
    def query(
        db: Session,
        *,
        case_id: str,
        file_id: Optional[str] = None,
        file_ids: Optional[Sequence[str]] = None,
        on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        description_contains: Optional[str] = None,
        search: Optional[str] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        abs_amount_compare: AbsoluteAmountCompare = "none",
        abs_amount_min: Optional[Decimal] = None,
        abs_amount_max: Optional[Decimal] = None,
        flow: Optional[str] = None,
        order_by: TransactionOrderBy = "date_asc",
        limit: int = 200,
        offset: int = 0,
    ) -> List[CaseFileTransaction]:
        page = CaseFileTransactionService.query_page(
            db,
            case_id=case_id,
            file_id=file_id,
            file_ids=file_ids,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            description_contains=description_contains,
            search=search,
            min_amount=min_amount,
            max_amount=max_amount,
            abs_amount_compare=abs_amount_compare,
            abs_amount_min=abs_amount_min,
            abs_amount_max=abs_amount_max,
            flow=flow,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return page.rows

    @staticmethod
    def query_page(
        db: Session,
        *,
        case_id: str,
        file_id: Optional[str] = None,
        file_ids: Optional[Sequence[str]] = None,
        on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        description_contains: Optional[str] = None,
        search: Optional[str] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        abs_amount_compare: AbsoluteAmountCompare = "none",
        abs_amount_min: Optional[Decimal] = None,
        abs_amount_max: Optional[Decimal] = None,
        flow: Optional[str] = None,
        order_by: TransactionOrderBy = "date_asc",
        limit: int = 5000,
        offset: int = 0,
    ) -> TransactionQueryPage:
        base = db.query(CaseFileTransaction)
        filtered = CaseFileTransactionService._apply_query_filters(
            base,
            case_id=case_id,
            file_id=file_id,
            file_ids=file_ids,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            description_contains=description_contains,
            search=search,
            min_amount=min_amount,
            max_amount=max_amount,
            abs_amount_compare=abs_amount_compare,
            abs_amount_min=abs_amount_min,
            abs_amount_max=abs_amount_max,
            flow=flow,
        )
        total = filtered.count()
        rows = (
            filtered.order_by(*_order_clause(order_by))
            .offset(max(0, offset))
            .limit(limit)
            .all()
        )
        return TransactionQueryPage(rows=rows, total=total)

    @staticmethod
    def fetch_ordered_by_ids(
        db: Session,
        *,
        case_id: str,
        file_id: str,
        transaction_ids: Sequence[str],
    ) -> List[CaseFileTransaction]:
        """Load transactions for export in the exact UI order; drop unknown ids."""
        ordered_ids = [str(tid).strip() for tid in transaction_ids if str(tid).strip()]
        if not ordered_ids:
            return []
        ordered_ids = ordered_ids[:10_000]
        rows = (
            db.query(CaseFileTransaction)
            .filter(
                CaseFileTransaction.case_id == case_id,
                CaseFileTransaction.file_id == file_id,
                CaseFileTransaction.id.in_(ordered_ids),
            )
            .all()
        )
        by_id = {row.id: row for row in rows}
        return [by_id[tid] for tid in ordered_ids if tid in by_id]

    @staticmethod
    def aggregate_totals(
        db: Session,
        *,
        case_id: str,
        file_id: Optional[str] = None,
        file_ids: Optional[Sequence[str]] = None,
        on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        description_contains: Optional[str] = None,
        search: Optional[str] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        abs_amount_compare: AbsoluteAmountCompare = "none",
        abs_amount_min: Optional[Decimal] = None,
        abs_amount_max: Optional[Decimal] = None,
        flow: Optional[str] = None,
    ) -> TransactionAggregateTotals:
        """COUNT + SUM over the filtered set without loading row payloads."""
        base = db.query(
            func.count(CaseFileTransaction.id),
            func.coalesce(func.sum(CaseFileTransaction.amount_rub), 0),
        )
        filtered = CaseFileTransactionService._apply_query_filters(
            base,
            case_id=case_id,
            file_id=file_id,
            file_ids=file_ids,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            description_contains=description_contains,
            search=search,
            min_amount=min_amount,
            max_amount=max_amount,
            abs_amount_compare=abs_amount_compare,
            abs_amount_min=abs_amount_min,
            abs_amount_max=abs_amount_max,
            flow=flow,
        )
        count_val, sum_val = filtered.one()
        amount_sum = sum_val if isinstance(sum_val, Decimal) else Decimal(str(sum_val or 0))
        return TransactionAggregateTotals(count=int(count_val or 0), amount_sum=amount_sum)

    @staticmethod
    def aggregate_by_description(
        db: Session,
        *,
        case_id: str,
        file_id: Optional[str] = None,
        file_ids: Optional[Sequence[str]] = None,
        on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        description_contains: Optional[str] = None,
        search: Optional[str] = None,
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        abs_amount_compare: AbsoluteAmountCompare = "none",
        abs_amount_min: Optional[Decimal] = None,
        abs_amount_max: Optional[Decimal] = None,
        flow: Optional[str] = None,
        order_by: DescriptionGroupOrderBy = "abs_sum_desc",
        limit: int = 10,
        min_op_count: int = 1,
    ) -> List[TransactionDescriptionGroup]:
        """Group filtered rows by description for counterparties / recurring payments."""
        desc_expr = func.coalesce(CaseFileTransaction.description, "")
        abs_sum_expr = func.coalesce(
            func.sum(func.abs(CaseFileTransaction.amount_rub)),
            0,
        )
        amount_sum_expr = func.coalesce(func.sum(CaseFileTransaction.amount_rub), 0)
        op_count_expr = func.count(CaseFileTransaction.id)

        base = db.query(
            desc_expr.label("description"),
            op_count_expr.label("op_count"),
            amount_sum_expr.label("amount_sum"),
            abs_sum_expr.label("abs_amount_sum"),
        )
        filtered = CaseFileTransactionService._apply_query_filters(
            base,
            case_id=case_id,
            file_id=file_id,
            file_ids=file_ids,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            description_contains=description_contains,
            search=search,
            min_amount=min_amount,
            max_amount=max_amount,
            abs_amount_compare=abs_amount_compare,
            abs_amount_min=abs_amount_min,
            abs_amount_max=abs_amount_max,
            flow=flow,
        )
        grouped = filtered.group_by(desc_expr).having(op_count_expr >= max(1, min_op_count))
        if order_by == "count_desc":
            grouped = grouped.order_by(op_count_expr.desc(), abs_sum_expr.desc())
        else:
            grouped = grouped.order_by(abs_sum_expr.desc(), op_count_expr.desc())

        rows = grouped.limit(max(1, limit)).all()
        out: List[TransactionDescriptionGroup] = []
        for row in rows:
            amount_sum = row.amount_sum if isinstance(row.amount_sum, Decimal) else Decimal(str(row.amount_sum or 0))
            abs_amount_sum = (
                row.abs_amount_sum
                if isinstance(row.abs_amount_sum, Decimal)
                else Decimal(str(row.abs_amount_sum or 0))
            )
            description = str(row.description or "").strip() or "—"
            out.append(
                TransactionDescriptionGroup(
                    description=description,
                    op_count=int(row.op_count or 0),
                    amount_sum=amount_sum,
                    abs_amount_sum=abs_amount_sum,
                )
            )
        return out

    @staticmethod
    def aggregate(
        db: Session,
        *,
        case_id: str,
        file_id: Optional[str] = None,
        file_ids: Optional[Sequence[str]] = None,
        on_date: Optional[date] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        description_contains: Optional[str] = None,
    ) -> Dict[str, Any]:
        totals = CaseFileTransactionService.aggregate_totals(
            db,
            case_id=case_id,
            file_id=file_id,
            file_ids=file_ids,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            description_contains=description_contains,
        )
        return {
            "count": totals.count,
            "amount_sum_rub": float(totals.amount_sum),
            "amount_sum_raw": str(totals.amount_sum),
        }


def parse_user_date(text: str) -> Optional[date]:
    """Parse DD.MM.YYYY from user or tool input."""
    return parse_operation_date(text or "")
