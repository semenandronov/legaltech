"""Operations registry — validation and access helpers."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.services.case_file_transaction_service import CaseFileTransactionService


def normalize_file_id(file_id: str | None) -> str:
    normalized = (file_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Параметр file_id обязателен")
    return normalized


def resolve_statement_file_id(
    db: Session,
    *,
    case_id: str,
    file_id: str | None,
) -> str:
    """Ensure the file belongs to the case and has ingested transaction rows."""
    normalized = normalize_file_id(file_id)
    if not CaseFileTransactionService.case_has_transactions(db, case_id, [normalized]):
        raise HTTPException(
            status_code=404,
            detail="Выписка не найдена в деле или ещё не оцифрована",
        )
    return normalized
