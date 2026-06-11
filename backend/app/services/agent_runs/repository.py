"""Persistence layer for agent_runs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.models.agent_run import AgentRun, AgentRunStatus
from app.models.case import Case


class AgentRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, run_id: str) -> Optional[AgentRun]:
        return self.db.query(AgentRun).filter(AgentRun.id == run_id).first()

    def get_for_user(self, run_id: str, user_id: str) -> Optional[AgentRun]:
        return (
            self.db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.user_id == user_id)
            .first()
        )

    def list_for_case(
        self,
        case_id: str,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AgentRun]:
        self.assert_case_access(case_id, user_id)
        return (
            self.db.query(AgentRun)
            .filter(AgentRun.case_id == case_id, AgentRun.user_id == user_id)
            .order_by(AgentRun.created_at.desc())
            .offset(max(0, offset))
            .limit(min(max(1, limit), 100))
            .all()
        )

    def list_pending_run_ids(self, limit: int = 8) -> List[str]:
        rows = (
            self.db.query(AgentRun.id)
            .filter(AgentRun.status == AgentRunStatus.PENDING)
            .order_by(AgentRun.created_at.asc())
            .limit(limit)
            .all()
        )
        return [str(r[0]) for r in rows]

    def list_resume_ready_run_ids(self, limit: int = 8) -> List[str]:
        """Runs with pending_resume payload waiting for worker claim."""
        rows = (
            self.db.query(AgentRun.id)
            .filter(
                AgentRun.status == AgentRunStatus.WAITING_FOR_USER,
                AgentRun.input_config.isnot(None),
            )
            .order_by(AgentRun.updated_at.asc())
            .limit(limit)
            .all()
        )
        out: List[str] = []
        for (run_id,) in rows:
            run = self.get_by_id(str(run_id))
            if run and isinstance(run.input_config, dict) and run.input_config.get("pending_resume"):
                out.append(str(run_id))
        return out

    def assert_case_access(self, case_id: str, user_id: str) -> Case:
        case = self.db.query(Case).filter(Case.id == case_id, Case.user_id == user_id).first()
        if not case:
            raise ValueError("case_not_found")
        return case

    def create(
        self,
        *,
        user_id: str,
        case_id: str,
        user_task: str,
        file_ids: Optional[List[str]] = None,
        input_config: Optional[Dict[str, Any]] = None,
    ) -> AgentRun:
        run_id = str(uuid.uuid4())
        run = AgentRun(
            id=run_id,
            case_id=case_id,
            user_id=user_id,
            thread_id=run_id,
            user_task=user_task,
            status=AgentRunStatus.PENDING,
            selected_file_ids=file_ids or [],
            input_config=input_config or {},
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    def try_claim_run(self, run_id: str, worker_instance_id: str) -> bool:
        """Atomically claim pending run for distributed worker execution."""
        now = self._utcnow()
        updated = (
            self.db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.status == AgentRunStatus.PENDING)
            .update(
                {
                    AgentRun.status: AgentRunStatus.RUNNING,
                    AgentRun.worker_instance_id: worker_instance_id,
                    AgentRun.started_at: now,
                    AgentRun.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        self.db.commit()
        return updated == 1

    def schedule_resume(self, run_id: str, resume_payload: Dict[str, Any]) -> bool:
        """Store resume payload while still waiting_for_user (worker will claim)."""
        run = self.get_by_id(run_id)
        if not run or run.status != AgentRunStatus.WAITING_FOR_USER:
            return False
        cfg = dict(run.input_config or {})
        cfg["pending_resume"] = resume_payload
        run.input_config = cfg
        run.updated_at = self._utcnow()
        self.db.commit()
        return True

    def try_claim_resume(self, run_id: str, worker_instance_id: str) -> bool:
        """Claim waiting_for_user run that has pending_resume."""
        run = self.get_by_id(run_id)
        if not run or run.status != AgentRunStatus.WAITING_FOR_USER:
            return False
        cfg = run.input_config if isinstance(run.input_config, dict) else {}
        if not cfg.get("pending_resume"):
            return False
        now = self._utcnow()
        updated = (
            self.db.query(AgentRun)
            .filter(
                AgentRun.id == run_id,
                AgentRun.status == AgentRunStatus.WAITING_FOR_USER,
            )
            .update(
                {
                    AgentRun.status: AgentRunStatus.RUNNING,
                    AgentRun.worker_instance_id: worker_instance_id,
                    AgentRun.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        self.db.commit()
        return updated == 1

    def pop_pending_resume(self, run: AgentRun) -> Optional[Dict[str, Any]]:
        cfg = dict(run.input_config or {})
        payload = cfg.pop("pending_resume", None)
        run.input_config = cfg
        self.db.commit()
        return payload if isinstance(payload, dict) else None

    def request_cancel(self, run_id: str) -> bool:
        run = self.get_by_id(run_id)
        if not run or run.status in AgentRunStatus.TERMINAL:
            return False
        run.cancel_requested_at = self._utcnow()
        run.updated_at = self._utcnow()
        self.db.commit()
        return True

    def cancel(self, run: AgentRun, *, message: str = "cancelled") -> None:
        run.status = AgentRunStatus.CANCELLED
        run.error_message = (message or "cancelled")[:4000]
        run.completed_at = self._utcnow()
        run.updated_at = self._utcnow()
        run.worker_instance_id = None
        self.db.commit()

    def is_cancel_requested(self, run: AgentRun) -> bool:
        return run.cancel_requested_at is not None and run.status not in AgentRunStatus.TERMINAL

    def mark_running(self, run: AgentRun) -> None:
        if run.status == AgentRunStatus.PENDING:
            run.status = AgentRunStatus.RUNNING
            run.started_at = run.started_at or self._utcnow()
            self.db.commit()

    def update_todos(self, run: AgentRun, todos: List[Dict[str, Any]]) -> None:
        run.todos = todos
        run.updated_at = self._utcnow()
        self.db.commit()

    def increment_tool_calls(self, run: AgentRun, delta: int = 1) -> None:
        run.total_tool_calls = int(run.total_tool_calls or 0) + delta
        run.updated_at = self._utcnow()
        self.db.commit()

    def complete(
        self,
        run: AgentRun,
        *,
        result_summary: Optional[str] = None,
        artifacts: Optional[Dict[str, Any]] = None,
    ) -> None:
        run.status = AgentRunStatus.COMPLETED
        run.result_summary = result_summary
        if artifacts is not None:
            run.artifacts = artifacts
        run.completed_at = self._utcnow()
        run.updated_at = self._utcnow()
        run.error_message = None
        self.db.commit()

    def fail(self, run: AgentRun, error_message: str) -> None:
        run.status = AgentRunStatus.FAILED
        run.error_message = (error_message or "unknown_error")[:4000]
        run.completed_at = self._utcnow()
        run.updated_at = self._utcnow()
        self.db.commit()

    def set_langfuse_trace_id(self, run: AgentRun, trace_id: str) -> None:
        run.langfuse_trace_id = (trace_id or "")[:64] or None
        run.updated_at = self._utcnow()
        self.db.commit()

    def set_waiting_for_user(self, run: AgentRun, payload: Dict[str, Any]) -> None:
        run.status = AgentRunStatus.WAITING_FOR_USER
        artifacts = dict(run.artifacts or {})
        artifacts["interrupt"] = payload
        run.artifacts = artifacts
        run.updated_at = self._utcnow()
        self.db.commit()
