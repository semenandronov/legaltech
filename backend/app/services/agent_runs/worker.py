"""Distributed agent run worker: claims runs, executes graph, publishes to event bus."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import uuid
from typing import Any, Dict, List, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.config import config
from app.models.agent_run import AgentRun, AgentRunStatus
from app.services.agent_runs.event_bus import AgentRunEventBus, TERMINAL_EVENT_TYPES
from app.services.agent_runs.event_policy import should_persist_stream_event
from app.services.agent_runs.event_channels import control_notify_channel
from app.services.agent_runs.event_store import AgentRunEventStore
from app.services.agent_runs.harness import AgentRunHarness, AgentRunHarnessContext
from app.services.agent_runs.postgres_listener import PostgresNotifyListener, emit_notify
from app.services.agent_runs.repository import AgentRunRepository
from app.services.agent_runs.schemas import AgentRunEventType, AgentRunStreamEvent
from app.services.agent_runs.artifact_collector import merge_artifact_items
from app.services.agent_runs.result_extractor import extract_final_assistant_from_agent
from app.services.agent_runs.stream_mapper import map_stream_part
from app.services.agent_runs.terminal_events import build_terminal_event
from app.services.agent_runs.tracing import agent_run_trace_scope
from app.services.observability.llm_langfuse_instrumentation import merge_langfuse_into_runnable_config
from app.utils.checkpointer_setup import get_async_postgres_checkpointer
from app.utils.database import SessionLocal

logger = logging.getLogger(__name__)

WORKER_INSTANCE_ID = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class AgentRunWorkerService:
    """Background worker for multi-pod agent execution."""

    def __init__(self) -> None:
        self.instance_id = WORKER_INSTANCE_ID
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._control_listener: Optional[PostgresNotifyListener] = None
        self._control_task: Optional[asyncio.Task] = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if not getattr(config, "AGENT_RUNS_WORKER_ENABLED", True):
            logger.info("Agent run worker disabled (AGENT_RUNS_WORKER_ENABLED=false)")
            return
        self._stopped.clear()
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._control_listener = PostgresNotifyListener([control_notify_channel()])
        await self._control_listener.start()
        self._control_task = asyncio.create_task(self._control_loop())
        logger.info("Agent run worker started instance_id=%s", self.instance_id)

    async def stop(self) -> None:
        self._stopped.set()
        for task in list(self._active_tasks.values()):
            task.cancel()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._control_task:
            self._control_task.cancel()
            try:
                await self._control_task
            except asyncio.CancelledError:
                pass
        if self._control_listener:
            await self._control_listener.stop()
        logger.info("Agent run worker stopped instance_id=%s", self.instance_id)

    async def _poll_loop(self) -> None:
        interval = float(getattr(config, "AGENT_RUNS_WORKER_POLL_SEC", 0.5) or 0.5)
        while not self._stopped.is_set():
            try:
                await self._scan_and_dispatch()
            except Exception as exc:
                logger.error("Agent run worker poll error: %s", exc, exc_info=True)
            await asyncio.sleep(interval)

    async def _scan_and_dispatch(self) -> None:
        db = SessionLocal()
        try:
            repo = AgentRunRepository(db)
            pending_ids = repo.list_pending_run_ids()
            resume_ids = repo.list_resume_ready_run_ids()
        finally:
            db.close()

        for run_id in pending_ids:
            if run_id in self._active_tasks:
                continue
            if await self._try_dispatch(run_id, mode="start"):
                continue

        for run_id in resume_ids:
            if run_id in self._active_tasks:
                continue
            await self._try_dispatch(run_id, mode="resume")

    async def _try_dispatch(self, run_id: str, *, mode: str) -> bool:
        db = SessionLocal()
        try:
            repo = AgentRunRepository(db)
            if mode == "start":
                claimed = repo.try_claim_run(run_id, self.instance_id)
            else:
                claimed = repo.try_claim_resume(run_id, self.instance_id)
            if not claimed:
                return False
        finally:
            db.close()

        task = asyncio.create_task(self._execute_claimed(run_id, mode=mode))
        self._active_tasks[run_id] = task
        task.add_done_callback(lambda _t, rid=run_id: self._active_tasks.pop(rid, None))
        return True

    async def _control_loop(self) -> None:
        if self._control_listener is None:
            return
        async for message in self._control_listener.events():
            if message.get("action") != "cancel":
                continue
            run_id = str(message.get("run_id") or "")
            if not run_id:
                continue
            task = self._active_tasks.get(run_id)
            if task is not None:
                task.cancel()
                logger.info("Cancel signal received for active run_id=%s on %s", run_id, self.instance_id)

    async def _execute_claimed(self, run_id: str, *, mode: str) -> None:
        db = SessionLocal()
        published_terminal = False
        try:
            repo = AgentRunRepository(db)
            run = repo.get_by_id(run_id)
            if not run or run.worker_instance_id != self.instance_id:
                return

            resume_payload = repo.pop_pending_resume(run) if mode == "resume" else None
            db.refresh(run)

            if mode == "resume" and resume_payload:
                graph_input: Any = Command(resume=resume_payload)
            else:
                graph_input = {"messages": [{"role": "user", "content": run.user_task}]}

            await self._run_graph(run, db, graph_input=graph_input)
            published_terminal = True
        except asyncio.CancelledError:
            await self._handle_cancel(run_id)
            published_terminal = True
            return
        except Exception as exc:
            logger.error("Worker execution failed run_id=%s: %s", run_id, exc, exc_info=True)
            await self._handle_fail(run_id, str(exc))
            published_terminal = True
        finally:
            if not published_terminal:
                await self._handle_fail(run_id, "worker exited without terminal event")
            db.close()

    async def _run_graph(self, run: AgentRun, db, *, graph_input: Any) -> None:
        repo = AgentRunRepository(db)

        def on_tool_completed() -> None:
            repo.increment_tool_calls(run)

        ctx = AgentRunHarnessContext(
            user_id=run.user_id,
            case_id=run.case_id,
            run_id=run.id,
            file_ids=list(run.selected_file_ids or []),
        )
        harness = AgentRunHarness(ctx, on_tool_completed=on_tool_completed)
        checkpointer = await self._resolve_checkpointer()
        agent = harness.create_agent(checkpointer=checkpointer)

        is_resume = isinstance(graph_input, Command)
        graph_config: Dict[str, Any] = merge_langfuse_into_runnable_config(
            {
                "configurable": {"thread_id": run.thread_id},
                "recursion_limit": int(getattr(config, "AGENT_RUNS_RECURSION_LIMIT", 50) or 50),
            },
            tags=["agent_runs", "deep_agent"],
            run_name=f"agent_run:{run.id}",
        )

        run_artifacts: Dict[str, Any] = dict(run.artifacts or {})
        trace_outcome: Dict[str, str] = {"status": "completed"}

        with agent_run_trace_scope(run, repo, resume=is_resume, outcome=trace_outcome):
            # No token streaming: only plan (todos) + tool lifecycle events for the UI.
            async for raw_part in agent.astream(
                graph_input,
                config=graph_config,
                stream_mode=["updates", "custom"],
            ):
                for event in map_stream_part(run.id, raw_part):
                    if event.type == AgentRunEventType.todos_updated and event.data:
                        todos = event.data.get("todos") or []
                        repo.update_todos(run, todos)
                    if event.type == AgentRunEventType.tool_completed and event.data:
                        artifact = event.data.get("artifact")
                        if isinstance(artifact, dict) and artifact.get("id"):
                            run_artifacts = merge_artifact_items(run_artifacts, artifact)
                            run.artifacts = run_artifacts
                            db.commit()
                    if should_persist_stream_event(event):
                        await AgentRunEventBus.publish(run.id, event)
                    if event.type == AgentRunEventType.interrupt:
                        repo.set_waiting_for_user(run, event.data or {})
                        trace_outcome["status"] = "waiting_for_user"
                        return

        state_config = {"configurable": {"thread_id": run.thread_id}}
        summary = (
            await self._extract_summary_with_retry(harness, checkpointer, agent, state_config)
        ).strip() or None
        if summary:
            await AgentRunEventBus.publish(
                run.id,
                AgentRunStreamEvent(
                    type=AgentRunEventType.text_delta,
                    run_id=run.id,
                    data={"text": summary},
                ),
            )
        artifacts_payload = run_artifacts if (run_artifacts.get("items")) else None
        repo.complete(run, result_summary=summary, artifacts=artifacts_payload)
        db.refresh(run)
        await AgentRunEventBus.publish(run.id, build_terminal_event(run))

    async def _handle_cancel(self, run_id: str) -> None:
        db = SessionLocal()
        try:
            repo = AgentRunRepository(db)
            run = repo.get_by_id(run_id)
            if not run or run.worker_instance_id != self.instance_id:
                return
            repo.cancel(run)
            db.refresh(run)
            await AgentRunEventBus.publish(
                run_id,
                AgentRunStreamEvent(
                    type=AgentRunEventType.run_cancelled,
                    run_id=run_id,
                    message="cancelled",
                    data={"status": run.status},
                ),
            )
        finally:
            db.close()

    async def _handle_fail(self, run_id: str, error: str) -> None:
        db = SessionLocal()
        try:
            repo = AgentRunRepository(db)
            run = repo.get_by_id(run_id)
            if not run:
                return
            if run.status not in AgentRunStatus.TERMINAL:
                repo.fail(run, error)
            db.refresh(run)
            await AgentRunEventBus.publish(run.id, build_terminal_event(run))
        finally:
            db.close()

    async def _extract_summary_with_retry(
        self,
        harness: AgentRunHarness,
        checkpointer: Any,
        live_agent: Any,
        state_config: Dict[str, Any],
    ) -> str:
        """Read final assistant text from checkpointer; Postgres flush can lag after astream."""
        for attempt in range(10):
            for candidate in (live_agent, harness.create_agent(checkpointer=checkpointer)):
                text = (await extract_final_assistant_from_agent(candidate, state_config)).strip()
                if text:
                    return text
            await asyncio.sleep(0.35 * (attempt + 1))
        return ""

    async def _resolve_checkpointer(self) -> Any:
        if getattr(config, "AGENT_RUNS_CHECKPOINTER_ENABLED", True):
            try:
                return await get_async_postgres_checkpointer()
            except Exception as exc:
                logger.warning("AsyncPostgresSaver unavailable, using MemorySaver: %s", exc)
        return MemorySaver()

_worker_singleton: Optional[AgentRunWorkerService] = None


def get_agent_run_worker() -> AgentRunWorkerService:
    global _worker_singleton
    if _worker_singleton is None:
        _worker_singleton = AgentRunWorkerService()
    return _worker_singleton


async def broadcast_cancel(run_id: str) -> None:
    await emit_notify(
        control_notify_channel(),
        {"action": "cancel", "run_id": run_id},
    )
