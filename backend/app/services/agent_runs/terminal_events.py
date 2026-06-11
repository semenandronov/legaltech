"""Terminal SSE events derived from agent_runs row state."""
from __future__ import annotations

from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.agent_runs.schemas import AgentRunEventType, AgentRunStreamEvent


def build_terminal_event(run: AgentRun) -> AgentRunStreamEvent:
    if run.status == AgentRunStatus.COMPLETED:
        return AgentRunStreamEvent(
            type=AgentRunEventType.run_completed,
            run_id=run.id,
            message="completed",
            data={
                "result_summary": run.result_summary,
                "artifacts": run.artifacts,
                "total_tool_calls": run.total_tool_calls,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            },
        )
    if run.status == AgentRunStatus.CANCELLED:
        return AgentRunStreamEvent(
            type=AgentRunEventType.run_cancelled,
            run_id=run.id,
            message=run.error_message or "cancelled",
            data={"status": run.status},
        )
    if run.status == AgentRunStatus.WAITING_FOR_USER:
        return AgentRunStreamEvent(
            type=AgentRunEventType.interrupt,
            run_id=run.id,
            message="waiting_for_user",
            data=run.artifacts or {},
        )
    return AgentRunStreamEvent(
        type=AgentRunEventType.run_failed,
        run_id=run.id,
        message=run.error_message or "failed",
        data={"status": run.status},
    )
