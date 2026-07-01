"""SQL/RAG/hybrid routing for tabular cell extraction (SQL-flagged files only)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.config import config
from app.services.chat.structured_data_router import (
    StructuredDataRouterResult,
    route_structured_data_plane,
)

if TYPE_CHECKING:
    from app.models.tabular_review import TabularColumn

logger = logging.getLogger(__name__)

_TABULAR_NUMERIC_COLUMN_TYPES = frozenset({"currency", "number"})


def tabular_cell_data_router_enabled() -> bool:
    return bool(
        getattr(config, "TABULAR_CELL_DATA_ROUTER_ENABLED", None)
        if hasattr(config, "TABULAR_CELL_DATA_ROUTER_ENABLED")
        else getattr(config, "TABULAR_STATEMENT_AGENT_ENABLED", True)
    )


def _column_information_need(column_type: str) -> str:
    if (column_type or "").strip().lower() in _TABULAR_NUMERIC_COLUMN_TYPES:
        return "tabular_aggregate"
    return "unknown"


def _enrich_question_for_router(
    question: str,
    *,
    file_id: str,
    column: "TabularColumn",
) -> str:
    label = (getattr(column, "column_label", None) or "").strip()
    column_type = str(getattr(column, "column_type", None) or "text")
    return (
        f"{question.strip()}\n\n"
        f"[Контекст tabular review: колонка «{label}», тип={column_type}; "
        f"ответ только по одному файлу id={file_id}]"
    )


def route_tabular_cell_data_plane(
    db: Session,
    *,
    case_id: str,
    file_id: str,
    column: "TabularColumn",
) -> StructuredDataRouterResult:
    """
    Decide rag / sql / hybrid for one tabular cell (single file scope).

    Reuses the same LLM router as case chat.
    """
    question = (getattr(column, "prompt", None) or getattr(column, "column_label", None) or "").strip()
    if not question:
        from app.services.chat.structured_data_router import _precondition_skip_result

        return _precondition_skip_result("empty_question")

    fid = str(file_id).strip()
    enriched = _enrich_question_for_router(question, file_id=fid, column=column)
    info_need = _column_information_need(str(getattr(column, "column_type", None) or "text"))

    result = route_structured_data_plane(
        db,
        case_id=str(case_id),
        question=enriched,
        attached_file_ids=[fid],
        eligible_sql_file_ids=[fid],
        scope_rag_file_ids=[fid],
        information_need=info_need,
    )
    logger.info(
        "[TabularCellRouter] case=%s file=%s column=%s plane=%s need=%s conf=%.2f",
        case_id,
        fid,
        getattr(column, "id", "?"),
        result.data_plane,
        result.information_need,
        result.confidence,
    )
    return result
