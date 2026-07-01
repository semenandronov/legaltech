"""Ingest and query structured-table rows (bank statements) for case assistant."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Sequence

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.config import config
from app.models.case_file_transaction import CaseFileTransaction
from app.services.structured_table_indexer import is_structured_table_document

logger = logging.getLogger(__name__)

_DATE_HEADER_RE = re.compile(
    r"(дата|date)",
    re.IGNORECASE,
)
_AMOUNT_HEADER_RE = re.compile(
    r"(сумм|amount|дебет|кредит)",
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


def feature_enabled() -> bool:
    return bool(getattr(config, "CASE_FILE_TRANSACTIONS_ENABLED", False))


def _pick_column(columns: Dict[str, str], pattern: re.Pattern[str]) -> Optional[str]:
    for key in columns:
        if pattern.search(key or ""):
            return key
    return None


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
    amount_key = _pick_column(normalized, _AMOUNT_HEADER_RE)
    desc_key = _pick_column(normalized, _DESCRIPTION_HEADER_RE)

    datetime_text = normalized.get(date_key, "") if date_key else None
    op_date = parse_operation_date(datetime_text or "")

    amount_raw = normalized.get(amount_key, "") if amount_key else None
    amount_rub, amount_raw_out = parse_amount_rub(amount_raw or "")

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
        amount_raw=amount_raw_out or None,
        description=(description or "").strip() or None,
        row_columns=normalized,
        page_start=int(metadata["page_start"]) if metadata.get("page_start") is not None else None,
        char_start=int(metadata["char_start"]) if metadata.get("char_start") is not None else None,
        char_end=int(metadata["char_end"]) if metadata.get("char_end") is not None else None,
    )


def rows_from_documents(documents: Sequence[Document]) -> List[ParsedTransactionRow]:
    parsed: List[ParsedTransactionRow] = []
    for doc in documents:
        md = doc.metadata or {}
        if md.get("chunk_level") != "row":
            continue
        row = parse_row_from_metadata(md)
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
    needle = (description_contains or "").strip().lower()

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
            ).lower()
            if needle not in hay:
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
        min_amount: Optional[Decimal] = None,
        max_amount: Optional[Decimal] = None,
        limit: int = 200,
    ) -> List[CaseFileTransaction]:
        q = db.query(CaseFileTransaction).filter(CaseFileTransaction.case_id == case_id)

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
        if description_contains:
            needle = f"%{description_contains.strip()}%"
            q = q.filter(CaseFileTransaction.description.ilike(needle))
        if min_amount is not None:
            q = q.filter(CaseFileTransaction.amount_rub >= min_amount)
        if max_amount is not None:
            q = q.filter(CaseFileTransaction.amount_rub <= max_amount)

        return (
            q.order_by(
                CaseFileTransaction.operation_date.asc().nullslast(),
                CaseFileTransaction.global_row_index.asc(),
            )
            .limit(limit)
            .all()
        )

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
        rows = CaseFileTransactionService.query(
            db,
            case_id=case_id,
            file_id=file_id,
            file_ids=file_ids,
            on_date=on_date,
            date_from=date_from,
            date_to=date_to,
            description_contains=description_contains,
            limit=10_000,
        )
        total = len(rows)
        amount_sum = sum((r.amount_rub for r in rows if r.amount_rub is not None), Decimal("0"))
        return {
            "count": total,
            "amount_sum_rub": float(amount_sum),
            "amount_sum_raw": str(amount_sum),
        }


def parse_user_date(text: str) -> Optional[date]:
    """Parse DD.MM.YYYY from user or tool input."""
    return parse_operation_date(text or "")
