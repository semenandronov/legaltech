"""Draft document tool — draft agent writer + DocumentEditor persist."""
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
from app.services.draft_agent.writer import (
    persist_draft_document,
    resolve_template_for_draft,
    write_draft_document_html,
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
    """Factory: creates document via draft agent writer (same engine as chat draft mode)."""

    @tool(TOOL_NAME, args_schema=DraftToolInput)
    async def agent_draft(
        user_prompt: str,
        file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Создаёт юридический черновик и сохраняет в редактор дела."""
        if not getattr(config, "AGENT_RUNS_DRAFT_TOOL_ENABLED", True):
            raise RuntimeError("agent_draft tool is disabled")

        payload = DraftToolInput(
            user_prompt=user_prompt,
            file_ids=file_ids,
        )

        emit_tool_started(
            TOOL_NAME,
            {
                "user_prompt": payload.user_prompt[:200],
                "file_count": len(file_ids or default_file_ids or []),
            },
        )

        db = SessionLocal()
        try:

            def _run_writer() -> Dict[str, Any]:
                template_html, template_label, _ = resolve_template_for_draft(
                    db,
                    template_file_id=None,
                    template_file_content=None,
                    user_question=payload.user_prompt,
                )
                html = write_draft_document_html(
                    document_instruction=payload.user_prompt,
                    template_html=template_html or None,
                    template_label=template_label,
                )
                title = payload.user_prompt.strip().split("\n")[0][:255] or "Новый документ"
                return persist_draft_document(
                    db,
                    case_id=case_id,
                    user_id=user_id,
                    title=title,
                    content=html,
                )

            async def _run_with_draft_timeout():
                timeout = _draft_timeout_sec()
                try:
                    return await asyncio.wait_for(
                        asyncio.to_thread(_run_writer),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError as exc:
                    raise TimeoutError(
                        f"{TOOL_NAME} превысил лимит {timeout:.0f} с"
                    ) from exc

            doc = await _run_with_draft_timeout()
            if not isinstance(doc, dict) or not doc.get("id"):
                emit_tool_completed(TOOL_NAME, success=False, output_summary="draft_write_failed")
                raise RuntimeError("draft_write_failed")

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
