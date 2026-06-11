"""Saved workflow scenarios per case."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import config
from app.models.user import User
from app.services.agent_runs.schemas import CaseWorkflowResponse, CreateCaseWorkflowRequest
from app.services.case_workflows.repository import CaseWorkflowRepository
from app.utils.auth import get_current_user
from app.utils.database import get_db

router = APIRouter(prefix="/cases/{case_id}/workflows", tags=["case-workflows"])


def _ensure_enabled() -> None:
    if not getattr(config, "AGENT_RUNS_ENABLED", True):
        raise HTTPException(status_code=503, detail="Workflows are disabled")


def _to_response(row) -> CaseWorkflowResponse:
    return CaseWorkflowResponse(
        id=row.id,
        case_id=row.case_id,
        title=row.title,
        description=row.description,
        user_task=row.user_task,
        default_file_ids=list(row.default_file_ids or []),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=list[CaseWorkflowResponse])
def list_case_workflows(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_enabled()
    repo = CaseWorkflowRepository(db)
    try:
        rows = repo.list_for_case(case_id, current_user.id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return [_to_response(r) for r in rows]


@router.post("", response_model=CaseWorkflowResponse, status_code=201)
def create_case_workflow(
    case_id: str,
    body: CreateCaseWorkflowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_enabled()
    repo = CaseWorkflowRepository(db)
    try:
        row = repo.create(
            case_id=case_id,
            user_id=current_user.id,
            title=body.title,
            user_task=body.user_task,
            description=body.description,
            default_file_ids=body.default_file_ids,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Дело не найдено")
    return _to_response(row)


@router.delete("/{workflow_id}", status_code=204)
def delete_case_workflow(
    case_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_enabled()
    repo = CaseWorkflowRepository(db)
    row = repo.get_for_user(workflow_id, current_user.id)
    if not row or row.case_id != case_id:
        raise HTTPException(status_code=404, detail="Сценарий не найден")
    repo.delete(workflow_id, current_user.id)
