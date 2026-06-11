"""Draft document tool — production draft_pipeline + DocumentEditor persist."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import tool

from app.config import config
from app.services.agent_runs.artifact_collector import artifact_from_tool_result
from app.services.agent_runs.schemas import DraftToolInput, DraftToolOutput
from app.services.agent_runs.tools._helpers import (
    emit_tool_completed,
    emit_tool_started,
    run_with_timeout,
)
from app.utils.database import SessionLocal

logger = logging.getLogger(__name__)

TOOL_NAME = "agent_draft"


def _draft_timeout_sec() -> float:
    return float(
        getattr(config, "AGENT_RUNS_DRAFT_TOOL_TIMEOUT_SEC", None)
        or getattr(config, "AGENT_RUNS_TOOL_TIMEOUT_SEC", 120)
        or 900
    )


def build_draft_tool(
    *,
    user_id: str,
    case_id: str,
    run_id: str,
    default_file_ids: List[str],
    on_tool_completed: Callable[[], None] | None = None,
) -> Any:
    """Factory: runs full draft_pipeline and persists to document editor."""

    @tool(TOOL_NAME, args_schema=DraftToolInput)
    async def agent_draft(
        user_prompt: str,
        template_system_id: Optional[str] = None,
        file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Создаёт юридический черновик через production draft pipeline и сохраняет в редактор дела."""
        if not getattr(config, "AGENT_RUNS_DRAFT_TOOL_ENABLED", True):
            raise RuntimeError("agent_draft tool is disabled")

        payload = DraftToolInput(
            user_prompt=user_prompt,
            template_system_id=template_system_id,
            file_ids=file_ids,
        )
        scope_file_ids = payload.file_ids if payload.file_ids else list(default_file_ids or [])

        emit_tool_started(
            TOOL_NAME,
            {
                "user_prompt": payload.user_prompt[:200],
                "file_count": len(scope_file_ids),
                "template_system_id": payload.template_system_id,
            },
        )

        db = SessionLocal()
        try:

            def _run_pipeline() -> Dict[str, Any]:
                from app.services.draft_pipeline.runner import execute_draft_pipeline

                state = {
                    "case_id": case_id,
                    "user_id": user_id,
                    "question": payload.user_prompt,
                    "attached_file_ids": scope_file_ids or None,
                    "template_system_id": payload.template_system_id,
                }
                return execute_draft_pipeline(state, db=db)

            async def _run_with_draft_timeout():
                timeout = _draft_timeout_sec()
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(_run_pipeline),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"{TOOL_NAME} превысил лимит {timeout:.0f} с"
                    ) from exc

            result = await _run_with_draft_timeout()
            doc = result.get("document_created") if isinstance(result, dict) else None
            errors = result.get("errors") if isinstance(result, dict) else None

            if not isinstance(doc, dict) or not doc.get("id"):
                message = "draft_pipeline_failed"
                if isinstance(errors, list) and errors:
                    message = str(errors[-1])[:500]
                elif isinstance(result, dict) and result.get("response"):
                    message = str(result.get("response"))[:500]
                emit_tool_completed(TOOL_NAME, success=False, output_summary=message)
                raise RuntimeError(message)

            output = DraftToolOutput(
                status="completed",
                document_id=str(doc["id"]),
                title=str(doc.get("title") or "Новый документ"),
                preview=str(doc.get("preview") or "")[:500],
                editor_path=f"/cases/{case_id}/editor/{doc['id']}",
                run_id=run_id,
            )
            response = output.model_dump()
            artifact = artifact_from_tool_result(TOOL_NAME, response, case_id=case_id)
            emit_tool_completed(
                TOOL_NAME,
                success=True,
                output_summary=f"Документ «{output.title}» создан (id={output.document_id})",
                artifact=artifact,
            )
            if on_tool_completed is not None:
                on_tool_completed()
            logger.info(
                "agent_draft completed run_id=%s document_id=%s",
                run_id,
                output.document_id,
            )
            return response
        except Exception as exc:
            emit_tool_completed(TOOL_NAME, success=False, output_summary=str(exc)[:500])
            logger.error("agent_draft failed run_id=%s: %s", run_id, exc, exc_info=True)
            raise
        finally:
            db.close()

    return agent_draft
