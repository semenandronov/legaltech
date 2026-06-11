"""Tabular review tool — create table, extract cells, return compact summary."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import tool

from app.services.agent_runs.artifact_collector import artifact_from_tool_result
from app.services.agent_runs.schemas import (
    TabularColumnSpec,
    TabularReviewToolInput,
    TabularReviewToolOutput,
)
from app.services.agent_runs.tools._helpers import (
    emit_tool_completed,
    emit_tool_started,
    run_with_timeout,
)
from app.services.tabular_review_service import TabularReviewService
from app.utils.database import SessionLocal

logger = logging.getLogger(__name__)

TOOL_NAME = "agent_tabular_review"
MAX_SUMMARY_ROWS = 24
MAX_CELL_CHARS = 480


def _compact_rows(table_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    col_by_id = {c["id"]: c["column_label"] for c in table_data.get("columns") or []}
    compact: List[Dict[str, Any]] = []
    for row in (table_data.get("rows") or [])[:MAX_SUMMARY_ROWS]:
        cells: Dict[str, Any] = {}
        for col_id, cell in (row.get("cells") or {}).items():
            label = col_by_id.get(col_id, col_id)
            value = cell.get("cell_value") if isinstance(cell, dict) else None
            if value is None:
                continue
            text = str(value).strip()
            if not text:
                continue
            if len(text) > MAX_CELL_CHARS:
                text = text[:MAX_CELL_CHARS] + "…"
            cells[label] = text
        compact.append(
            {
                "file_id": row.get("file_id"),
                "file_name": row.get("file_name"),
                "cells": cells,
            }
        )
    return compact


def build_tabular_review_tool(
    *,
    user_id: str,
    case_id: str,
    run_id: str,
    default_file_ids: List[str],
    on_tool_completed: Callable[[], None] | None = None,
) -> Any:
    """Factory: binds case scope and metrics hook."""

    @tool(TOOL_NAME, args_schema=TabularReviewToolInput)
    async def agent_tabular_review(
        review_name: str,
        columns: List[TabularColumnSpec],
        description: Optional[str] = None,
        file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Создаёт таблицу по делу, извлекает значения по колонкам из документов и возвращает сводку."""
        payload = TabularReviewToolInput(
            review_name=review_name,
            columns=columns,
            description=description,
            file_ids=file_ids,
        )
        scope_file_ids = payload.file_ids if payload.file_ids else list(default_file_ids or [])
        preview = {
            "review_name": payload.review_name[:80],
            "columns": [c.column_label for c in payload.columns],
            "file_count": len(scope_file_ids),
        }
        emit_tool_started(TOOL_NAME, preview)

        db = SessionLocal()
        try:
            service = TabularReviewService(db)
            review = service.create_tabular_review(
                case_id=case_id,
                user_id=user_id,
                name=payload.review_name,
                description=payload.description,
                selected_file_ids=scope_file_ids or None,
            )

            for col in payload.columns:
                service.add_column(
                    review_id=review.id,
                    column_label=col.column_label,
                    column_type=col.column_type,
                    prompt=col.prompt,
                    user_id=user_id,
                )

            extraction = await run_with_timeout(
                service.run_extraction(review.id, user_id),
                label=TOOL_NAME,
            )
            table_data = service.get_table_data(review.id, user_id)
            rows = _compact_rows(table_data)

            output = TabularReviewToolOutput(
                status="completed",
                review_id=review.id,
                review_name=review.name,
                saved_count=int(extraction.get("saved_count") or 0),
                error_count=int(extraction.get("error_count") or 0),
                total_tasks=int(extraction.get("total_tasks") or 0),
                rows=rows,
            )
            result = output.model_dump()
            artifact = artifact_from_tool_result(TOOL_NAME, result, case_id=case_id)
            emit_tool_completed(
                TOOL_NAME,
                success=True,
                output_summary=f"{review.name}: {output.saved_count} ячеек, {len(rows)} строк",
                artifact=artifact,
            )
            if on_tool_completed is not None:
                on_tool_completed()
            logger.info(
                "agent_tabular_review completed run_id=%s review_id=%s saved=%s",
                run_id,
                review.id,
                output.saved_count,
            )
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_NAME, success=False, output_summary=str(exc)[:500])
            logger.error("agent_tabular_review failed run_id=%s: %s", run_id, exc, exc_info=True)
            raise
        finally:
            db.close()

    return agent_tabular_review
