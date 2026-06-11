"""Sync DB helpers for agent-run HTTP routes (run in thread pool)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.agent_runs.repository import AgentRunRepository
from app.services.agent_runs.schemas import (
    AgentRunDetailResponse,
    AgentRunListItem,
    AgentRunListResponse,
    AgentRunResponse,
    AgentRunStatusEnum,
    CreateAgentRunRequest,
    ResumeAgentRunRequest,
)
from app.services.agent_runs.terminal_events import build_terminal_event
from app.utils.database import SessionLocal


def list_agent_runs_for_case(
    case_id: str,
    user_id: str,
    *,
    limit: int,
    offset: int,
) -> AgentRunListResponse:
    db = SessionLocal()
    try:
        rows = AgentRunRepository(db).list_for_case(case_id, user_id, limit=limit, offset=offset)
        items = [
            AgentRunListItem(
                id=r.id,
                case_id=r.case_id,
                status=AgentRunStatusEnum(r.status),
                user_task=r.user_task,
                result_summary=r.result_summary,
                error_message=r.error_message,
                total_tool_calls=int(r.total_tool_calls or 0),
                created_at=r.created_at,
                completed_at=r.completed_at,
            )
            for r in rows
        ]
        return AgentRunListResponse(items=items, total=len(items))
    finally:
        db.close()


def create_agent_run_record(user_id: str, body: CreateAgentRunRequest) -> AgentRunResponse:
    db = SessionLocal()
    try:
        repo = AgentRunRepository(db)
        repo.assert_case_access(body.case_id, user_id)
        run = repo.create(
            user_id=user_id,
            case_id=body.case_id,
            user_task=body.user_task,
            file_ids=body.file_ids,
            input_config=body.input_config,
        )
        return AgentRunResponse(
            id=run.id,
            case_id=run.case_id,
            thread_id=run.thread_id,
            status=AgentRunStatusEnum(run.status),
            user_task=run.user_task,
            created_at=run.created_at,
        )
    finally:
        db.close()


def get_agent_run_detail(run_id: str, user_id: str) -> Optional[AgentRunDetailResponse]:
    db = SessionLocal()
    try:
        run = AgentRunRepository(db).get_for_user(run_id, user_id)
        if not run:
            return None
        return AgentRunDetailResponse(
            id=run.id,
            case_id=run.case_id,
            thread_id=run.thread_id,
            status=AgentRunStatusEnum(run.status),
            user_task=run.user_task,
            created_at=run.created_at,
            selected_file_ids=run.selected_file_ids,
            todos=run.todos,
            artifacts=run.artifacts,
            result_summary=run.result_summary,
            error_message=run.error_message,
            total_tool_calls=int(run.total_tool_calls or 0),
            started_at=run.started_at,
            completed_at=run.completed_at,
        )
    finally:
        db.close()


def request_cancel_run(run_id: str, user_id: str) -> Tuple[bool, str]:
    """Returns (found, cancelled_ok)."""
    db = SessionLocal()
    try:
        repo = AgentRunRepository(db)
        run = repo.get_for_user(run_id, user_id)
        if not run:
            return False, "not_found"
        if not repo.request_cancel(run_id):
            return True, "already_terminal"
        return True, "cancel_requested"
    finally:
        db.close()


def prepare_stream_resume(
    run_id: str,
    user_id: str,
    resume: ResumeAgentRunRequest,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Returns (status, error_payload).
    status: ok | not_found | terminal | not_waiting | schedule_failed
    """
    db = SessionLocal()
    try:
        repo = AgentRunRepository(db)
        run = repo.get_for_user(run_id, user_id)
        if not run:
            return "not_found", None
        if run.status in AgentRunStatus.TERMINAL:
            return "terminal", build_terminal_event(run).model_dump(mode="json")
        if run.status != AgentRunStatus.WAITING_FOR_USER:
            return "not_waiting", {"status": run.status}
        resume_value: Dict[str, Any] = {"approved": resume.approved}
        if resume.payload:
            resume_value.update(resume.payload)
        if not repo.schedule_resume(run_id, resume_value):
            return "schedule_failed", None
        return "ok", None
    finally:
        db.close()


def get_stream_run_gate(run_id: str, user_id: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Returns (status, terminal_payload).
    status: ok | not_found | terminal | waiting
    """
    db = SessionLocal()
    try:
        repo = AgentRunRepository(db)
        run = repo.get_for_user(run_id, user_id)
        if not run:
            return "not_found", None
        if run.status in AgentRunStatus.TERMINAL:
            return "terminal", build_terminal_event(run).model_dump(mode="json")
        if run.status == AgentRunStatus.WAITING_FOR_USER:
            return "waiting", build_terminal_event(run).model_dump(mode="json")
        return "ok", None
    finally:
        db.close()


def terminal_if_no_events(run_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        from app.services.agent_runs.event_store import AgentRunEventStore

        repo = AgentRunRepository(db)
        run = repo.get_for_user(run_id, user_id)
        if run and run.status in AgentRunStatus.TERMINAL:
            if AgentRunEventStore(db).max_seq(run_id) == 0:
                return build_terminal_event(run).model_dump(mode="json")
        return None
    finally:
        db.close()
