"""
Summary-first overview path for case corpus questions.

Builds one synthetic Document per case file from upload-time passports
(doc_summary_short, key_points) — avoids random chunk RAG for global overview.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document
from sqlalchemy.orm import Session

from app.services.chat.retrieval_router import build_case_file_catalog
from app.services.observability.case_assistant_langfuse_tracing import case_assistant_span

logger = logging.getLogger(__name__)


def overview_summary_path_enabled() -> bool:
    from app.config import config

    return bool(getattr(config, "CASE_ASSISTANT_OVERVIEW_SUMMARY_PATH_ENABLED", True))


def _format_overview_passage(
    *,
    filename: str,
    doc_type: str,
    summary: str,
    key_points: List[str],
) -> str:
    lines = [f"Файл: {filename}"]
    if doc_type and doc_type != "other":
        lines.append(f"Тип: {doc_type}")
    if summary:
        lines.append(f"Краткое содержание: {summary.strip()}")
    if key_points:
        points = "; ".join(p.strip() for p in key_points[:8] if p and str(p).strip())
        if points:
            lines.append(f"Ключевые пункты: {points}")
    return "\n".join(lines)


def build_summary_overview_documents(
    db: Session,
    *,
    case_id: str,
    file_ids: Optional[List[str]] = None,
    limit: int = 80,
) -> Tuple[List[Document], Dict[str, Any]]:
    """Return one overview Document per case file (passport summaries)."""
    meta: Dict[str, Any] = {
        "strategy": "summary_overview",
        "pipeline": True,
        "recall_k": 0,
    }
    catalog = build_case_file_catalog(db, case_id, limit=max(1, min(int(limit), 200)))
    if file_ids:
        allow = {str(x) for x in file_ids if str(x).strip()}
        catalog = [e for e in catalog if e.file_id in allow]

    docs: List[Document] = []
    for entry in catalog:
        summary = (entry.summary or "").strip()
        if not summary and not entry.key_points:
            continue
        passage = _format_overview_passage(
            filename=entry.filename,
            doc_type=entry.doc_type,
            summary=summary,
            key_points=list(entry.key_points or []),
        )
        docs.append(
            Document(
                page_content=passage,
                metadata={
                    "file_id": entry.file_id,
                    "filename": entry.filename,
                    "doc_type": entry.doc_type,
                    "source_type": "case_file_passport",
                    "chunk_level": "passport",
                    "overview_score": 1.0,
                    "combined_score": 1.0,
                },
            )
        )

    meta["recall_docs"] = len(docs)
    meta["scoped_files_count"] = len(docs)
    meta["scope_mode"] = "passport_overview"
    logger.info(
        "[CaseOverview] summary path case=%s files=%s docs=%s",
        case_id,
        len(catalog),
        len(docs),
    )
    return docs, meta


def run_summary_overview_recall(
    *,
    db: Session,
    case_id: str,
    retrieval_file_ids: Optional[List[str]] = None,
) -> Tuple[List[Document], Dict[str, Any]]:
    with case_assistant_span(
        "summary_overview_recall",
        metadata={"case_id": case_id},
    ) as span_out:
        docs, meta = build_summary_overview_documents(
            db,
            case_id=str(case_id),
            file_ids=retrieval_file_ids,
        )
        span_out["docs_count"] = len(docs)
        span_out["scope_mode"] = meta.get("scope_mode")
    return docs, meta
