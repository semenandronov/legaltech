"""CRUD for saved case workflow scenarios."""
from __future__ import annotations

from typing import List, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.case_workflow import CaseWorkflow
from app.services.agent_runs.repository import AgentRunRepository


class CaseWorkflowRepository:
    def __init__(self, db: Session):
        self.db = db
        self._cases = AgentRunRepository(db)

    def list_for_case(self, case_id: str, user_id: str) -> List[CaseWorkflow]:
        self._cases.assert_case_access(case_id, user_id)
        return (
            self.db.query(CaseWorkflow)
            .filter(CaseWorkflow.case_id == case_id, CaseWorkflow.user_id == user_id)
            .order_by(CaseWorkflow.updated_at.desc())
            .all()
        )

    def get_for_user(self, workflow_id: str, user_id: str) -> Optional[CaseWorkflow]:
        return (
            self.db.query(CaseWorkflow)
            .filter(CaseWorkflow.id == workflow_id, CaseWorkflow.user_id == user_id)
            .first()
        )

    def create(
        self,
        *,
        case_id: str,
        user_id: str,
        title: str,
        user_task: str,
        description: Optional[str] = None,
        default_file_ids: Optional[List[str]] = None,
    ) -> CaseWorkflow:
        self._cases.assert_case_access(case_id, user_id)
        row = CaseWorkflow(
            id=str(uuid.uuid4()),
            case_id=case_id,
            user_id=user_id,
            title=title.strip(),
            description=(description or "").strip() or None,
            user_task=user_task.strip(),
            default_file_ids=default_file_ids or [],
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, workflow_id: str, user_id: str) -> bool:
        row = self.get_for_user(workflow_id, user_id)
        if not row:
            return False
        self.db.delete(row)
        self.db.commit()
        return True
