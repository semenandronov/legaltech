"""Chat tools for structured-table transaction queries (bank statements)."""

from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.models.case import File as FileModel
from app.models.case_file_transaction import CaseFileTransaction
from app.services.case_file_transaction_service import (
    CaseFileTransactionService,
    feature_enabled,
    format_db_row_for_agent,
    parse_user_date,
)

logger = logging.getLogger(__name__)

_db: Optional[Session] = None
_case_id: Optional[str] = None
_attached_file_ids: Optional[List[str]] = None
_citation_rows: List[CaseFileTransaction] = []


def reset_transaction_tool_citation_rows() -> None:
    """Clear rows collected during the current agent turn (for citations)."""
    global _citation_rows
    _citation_rows = []


def pop_transaction_tool_citation_rows() -> List[CaseFileTransaction]:
    """Return and clear rows cited by tools in the current turn."""
    global _citation_rows
    rows = list(_citation_rows)
    _citation_rows = []
    return rows


def _record_citation_rows(rows: Sequence[CaseFileTransaction]) -> None:
    global _citation_rows
    seen = {r.id for r in _citation_rows}
    for row in rows:
        if row.id not in seen:
            _citation_rows.append(row)
            seen.add(row.id)


def initialize_case_transaction_tools(
    *,
    db: Session,
    case_id: str,
    attached_file_ids: Optional[List[str]] = None,
) -> None:
    global _db, _case_id, _attached_file_ids
    _db = db
    _case_id = case_id
    _attached_file_ids = attached_file_ids


def _resolve_scope_file_ids() -> Optional[List[str]]:
    if not _db or not _case_id:
        return None
    if _attached_file_ids:
        tx_ids = set(CaseFileTransactionService.list_transaction_file_ids(_db, _case_id))
        scoped = [fid for fid in _attached_file_ids if fid in tx_ids]
        return scoped or None
    return CaseFileTransactionService.list_transaction_file_ids(_db, _case_id)


def _file_label(file_id: str) -> str:
    if not _db:
        return file_id
    row = _db.query(FileModel).filter(FileModel.id == file_id).first()
    return row.filename if row and row.filename else file_id


@tool
def list_case_transactions(
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
    description_contains: str = "",
    filename: str = "",
    limit: int = 100,
) -> str:
    """
    Полный список операций из банковских выписок и реестров платежей в деле (SQL, не семантический поиск).

    ИСПОЛЬЗУЙ когда пользователь спрашивает про операции, платежи, переводы, выписку —
    в том числе если в вопросе только дата/время (например «11.06.2026 19:28 что было?»).
    Допускай опечатки в словах («транзкакция», «оперция»).

    НЕ используй для договоров, исков, пунктов договора и смыслового анализа текста.

    Args:
        on_date: дата DD.MM.YYYY (например 24.06.2026)
        date_from: начало периода DD.MM.YYYY
        date_to: конец периода DD.MM.YYYY
        description_contains: токен в описании (например YANDEX, Иванов, VK) —
            целое слово/код, не произвольная подстрока
        filename: имя файла выписки (необязательно)
        limit: максимум строк в ответе (по умолчанию 100)
    """
    if not feature_enabled() or not _db or not _case_id:
        return "Индекс операций по выпискам отключён или контекст дела недоступен."

    scope_file_ids = _resolve_scope_file_ids()
    if not scope_file_ids:
        return (
            "В этом деле нет распарсенных выписок с таблицей операций. "
            "Используй search_in_documents для поиска по документам."
        )

    file_id: Optional[str] = None
    if filename.strip():
        match = (
            _db.query(FileModel)
            .filter(FileModel.case_id == _case_id)
            .filter(FileModel.filename.ilike(f"%{filename.strip()}%"))
            .first()
        )
        if not match:
            return f"Файл «{filename}» не найден в деле."
        if match.id not in scope_file_ids:
            return (
                f"Файл «{match.filename}» не является выпиской с таблицей операций. "
                "Используй search_in_documents."
            )
        file_id = match.id

    rows = CaseFileTransactionService.query(
        _db,
        case_id=_case_id,
        file_id=file_id,
        file_ids=scope_file_ids if not file_id else None,
        on_date=parse_user_date(on_date) if on_date.strip() else None,
        date_from=parse_user_date(date_from) if date_from.strip() else None,
        date_to=parse_user_date(date_to) if date_to.strip() else None,
        description_contains=description_contains.strip() or None,
        limit=max(1, min(int(limit or 100), 500)),
    )

    if not rows:
        return "Операции по заданным фильтрам не найдены."

    _record_citation_rows(rows)

    lines = [f"Найдено операций: {len(rows)}"]
    for row in rows:
        lines.append(format_db_row_for_agent(row, file_label=_file_label(row.file_id)))

    logger.info(
        "[CaseTransactionTools] list_case_transactions case=%s count=%s",
        _case_id,
        len(rows),
    )
    return "\n".join(lines)


@tool
def aggregate_case_transactions(
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
    description_contains: str = "",
    filename: str = "",
) -> str:
    """
    Подсчёт и сумма операций из банковских выписок в деле.

    ИСПОЛЬЗУЙ для вопросов «сколько операций», «общая сумма за период», «итого за дату».
    НЕ используй для договоров и произвольных документов — только выписки с таблицей операций.

    Args:
        on_date: дата DD.MM.YYYY
        date_from: начало периода DD.MM.YYYY
        date_to: конец периода DD.MM.YYYY
        description_contains: фильтр по описанию
        filename: имя файла выписки (необязательно)
    """
    if not feature_enabled() or not _db or not _case_id:
        return "Индекс операций по выпискам отключён или контекст дела недоступен."

    scope_file_ids = _resolve_scope_file_ids()
    if not scope_file_ids:
        return "В деле нет распарсенных выписок. Используй search_in_documents."

    file_id: Optional[str] = None
    if filename.strip():
        match = (
            _db.query(FileModel)
            .filter(FileModel.case_id == _case_id)
            .filter(FileModel.filename.ilike(f"%{filename.strip()}%"))
            .first()
        )
        if not match:
            return f"Файл «{filename}» не найден."
        file_id = match.id

    agg = CaseFileTransactionService.aggregate(
        _db,
        case_id=_case_id,
        file_id=file_id,
        file_ids=scope_file_ids if not file_id else None,
        on_date=parse_user_date(on_date) if on_date.strip() else None,
        date_from=parse_user_date(date_from) if date_from.strip() else None,
        date_to=parse_user_date(date_to) if date_to.strip() else None,
        description_contains=description_contains.strip() or None,
    )

    parts = [
        f"Количество операций: {agg['count']}",
        f"Сумма (руб.): {agg['amount_sum_raw']}",
    ]
    if on_date.strip():
        parts.insert(0, f"Период: дата {on_date.strip()}")
    elif date_from.strip() or date_to.strip():
        parts.insert(0, f"Период: {date_from or '…'} — {date_to or '…'}")

    if agg["count"] > 0:
        sample_rows = CaseFileTransactionService.query(
            _db,
            case_id=_case_id,
            file_id=file_id,
            file_ids=scope_file_ids if not file_id else None,
            on_date=parse_user_date(on_date) if on_date.strip() else None,
            date_from=parse_user_date(date_from) if date_from.strip() else None,
            date_to=parse_user_date(date_to) if date_to.strip() else None,
            description_contains=description_contains.strip() or None,
            limit=min(int(agg["count"]), 50),
        )
        _record_citation_rows(sample_rows)

    return "\n".join(parts)


def get_case_transaction_tools(
    db: Session,
    case_id: str,
    attached_file_ids: Optional[List[str]] = None,
) -> List:
    """Return transaction tools only when the case has ingested structured-table rows."""
    if not feature_enabled():
        return []
    scope = attached_file_ids or CaseFileTransactionService.list_transaction_file_ids(db, case_id)
    if not scope:
        return []
    if attached_file_ids and not CaseFileTransactionService.case_has_transactions(
        db, case_id, attached_file_ids
    ):
        return []
    if not attached_file_ids and not CaseFileTransactionService.case_has_transactions(db, case_id):
        return []

    initialize_case_transaction_tools(
        db=db,
        case_id=case_id,
        attached_file_ids=attached_file_ids,
    )
    return [list_case_transactions, aggregate_case_transactions]
