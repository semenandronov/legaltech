"""HTTP API for deep agent runs (Legora-style orchestration)."""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import config
from app.services.agent_runs.executor import AgentRunExecutor
from app.services.agent_runs.route_db import (
    create_agent_run_record,
    get_agent_run_detail,
    list_agent_runs_for_case,
    request_cancel_run,
)
from app.services.agent_runs.worker import broadcast_cancel, get_agent_run_worker
from app.services.agent_runs.schemas import (
    AgentRunDetailResponse,
    AgentRunListResponse,
    AgentRunResponse,
    CreateAgentRunRequest,
    ResumeAgentRunRequest,
)
from app.utils.auth import get_current_user
from app.utils.sync_db_pool import run_sync_db
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])


def _ensure_enabled() -> None:
    if not getattr(config, "AGENT_RUNS_ENABLED", True):
        raise HTTPException(status_code=503, detail="Agent runs are disabled")


@router.get("", response_model=AgentRunListResponse)
def list_agent_runs(
    case_id: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    """History of workflow runs for a case."""
    _ensure_enabled()
    try:
        return list_agent_runs_for_case(case_id, current_user.id, limit=limit, offset=offset)
    except ValueError:
        raise HTTPException(status_code=404, detail="Дело не найдено")


@router.post("", response_model=AgentRunResponse, status_code=201)
def create_agent_run(
    body: CreateAgentRunRequest,
    current_user: User = Depends(get_current_user),
):
    _ensure_enabled()
    try:
        return create_agent_run_record(current_user.id, body)
    except ValueError:
        raise HTTPException(status_code=404, detail="Дело не найдено")


@router.get("/{run_id}", response_model=AgentRunDetailResponse)
def get_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    _ensure_enabled()
    detail = get_agent_run_detail(run_id, current_user.id)
    if not detail:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return detail


@router.post("/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    """Request distributed cancel; active worker pod will abort the run."""
    _ensure_enabled()
    found, outcome = await run_sync_db(request_cancel_run, run_id, current_user.id)
    if not found:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    if outcome == "already_terminal":
        raise HTTPException(status_code=409, detail="Запуск уже завершён")
    await broadcast_cancel(run_id)
    _ = get_agent_run_worker()
    return {"status": "cancel_requested", "run_id": run_id}


@router.post("/{run_id}/resume")
async def resume_agent_run(
    run_id: str,
    body: ResumeAgentRunRequest,
    current_user: User = Depends(get_current_user),
):
    """Resume a run after HITL interrupt; streams the same SSE event types as /stream."""
    _ensure_enabled()
    executor = AgentRunExecutor()

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in executor.stream_resume(run_id, current_user.id, body):
                yield chunk
        except Exception as exc:
            logger.error("SSE resume generator error run_id=%s: %s", run_id, exc, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}/stream")
async def stream_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
):
    _ensure_enabled()
    executor = AgentRunExecutor()

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for chunk in executor.stream(run_id, current_user.id):
                yield chunk
        except Exception as exc:
            logger.error("SSE generator error run_id=%s: %s", run_id, exc, exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'run_id': run_id, 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
