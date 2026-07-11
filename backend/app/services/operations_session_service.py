"""Load/save operations registry UI sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.case import File
from app.models.operations_statement_session import OperationsStatementSession


def get_session(
    db: Session,
    *,
    user_id: str,
    case_id: str,
    file_id: str,
) -> Optional[OperationsStatementSession]:
    return (
        db.query(OperationsStatementSession)
        .filter(
            OperationsStatementSession.user_id == user_id,
            OperationsStatementSession.case_id == case_id,
            OperationsStatementSession.file_id == file_id,
        )
        .first()
    )


def touch_session(
    db: Session,
    *,
    user_id: str,
    case_id: str,
    file_id: str,
    filename: Optional[str] = None,
    ui_state: Optional[Dict[str, Any]] = None,
) -> OperationsStatementSession:
    row = get_session(db, user_id=user_id, case_id=case_id, file_id=file_id)
    if row is None:
        if not filename:
            file_row = (
                db.query(File)
                .filter(File.id == file_id, File.case_id == case_id)
                .first()
            )
            filename = file_row.filename if file_row else None
        row = OperationsStatementSession(
            user_id=user_id,
            case_id=case_id,
            file_id=file_id,
            filename=filename,
            ui_state=ui_state or {},
        )
        db.add(row)
    else:
        if filename:
            row.filename = filename
        if ui_state is not None:
            row.ui_state = ui_state
        row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def save_ui_state(
    db: Session,
    *,
    user_id: str,
    case_id: str,
    file_id: str,
    ui_state: Dict[str, Any],
    filename: Optional[str] = None,
) -> OperationsStatementSession:
    return touch_session(
        db,
        user_id=user_id,
        case_id=case_id,
        file_id=file_id,
        filename=filename,
        ui_state=ui_state,
    )


def list_sessions_for_case(
    db: Session,
    *,
    user_id: str,
    case_id: str,
    limit: int = 50,
) -> list[OperationsStatementSession]:
    return (
        db.query(OperationsStatementSession)
        .filter(
            OperationsStatementSession.user_id == user_id,
            OperationsStatementSession.case_id == case_id,
        )
        .order_by(OperationsStatementSession.updated_at.desc())
        .limit(limit)
        .all()
    )
