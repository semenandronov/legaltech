"""Langfuse trace lifecycle for agent runs."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.models.agent_run import AgentRun
from app.services.agent_runs.repository import AgentRunRepository
from app.services.observability.langfuse_service import (
    TraceContext,
    create_trace_context,
    end_trace,
    langfuse_enabled,
    reset_active_trace_context,
    set_active_trace_context,
)


def _build_trace_metadata(run: AgentRun) -> Dict[str, Any]:
    return {
        "feature": "agent_runs",
        "run_id": run.id,
        "case_id": run.case_id,
        "thread_id": run.thread_id,
        "user_task_preview": (run.user_task or "")[:500],
        "selected_file_ids_count": len(run.selected_file_ids or []),
    }


@contextmanager
def agent_run_trace_scope(
    run: AgentRun,
    repo: AgentRunRepository,
    *,
    resume: bool = False,
    outcome: Optional[Dict[str, str]] = None,
) -> Iterator[Optional[TraceContext]]:
    """Bind Langfuse trace to the current async task; persist trace_id on first run."""
    if not langfuse_enabled():
        yield None
        return

    trace_id = run.langfuse_trace_id or run.id
    trace_ctx = create_trace_context(
        name="agent_run_resume" if resume else "agent_run",
        user_id=run.user_id,
        session_id=run.thread_id,
        metadata=_build_trace_metadata(run),
        tags=["agent_runs", "deep_agent"],
        input_payload={"user_task": run.user_task, "resume": resume},
        trace_id=trace_id,
    )
    token = set_active_trace_context(trace_ctx)
    if not run.langfuse_trace_id:
        repo.set_langfuse_trace_id(run, trace_ctx.trace_id)

    status = "completed"
    error: Optional[str] = None
    try:
        yield trace_ctx
        if outcome and outcome.get("status"):
            status = str(outcome["status"])
    except Exception as exc:
        status = "failed"
        error = str(exc)
        raise
    finally:
        end_trace(trace_ctx, status=status, error=error)
        reset_active_trace_context(token)
