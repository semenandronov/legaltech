"""Case document RAG search tool for deep agents."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import tool

from app.services.agent_runs.schemas import CaseRagToolInput, CaseRagToolOutput, RagHit
from app.services.agent_runs.tools._helpers import (
    emit_tool_completed,
    emit_tool_started,
    run_with_timeout,
)
from app.services.rag_service import RAGService
from app.utils.database import SessionLocal

logger = logging.getLogger(__name__)

TOOL_NAME = "agent_case_search"
MAX_SNIPPET_CHARS = 900


def _format_hits(documents: List[Any]) -> List[RagHit]:
    hits: List[RagHit] = []
    for doc in documents:
        meta = doc.metadata or {}
        text = (doc.page_content or "").strip()
        if not text:
            continue
        if len(text) > MAX_SNIPPET_CHARS:
            text = text[:MAX_SNIPPET_CHARS] + "…"
        hits.append(
            RagHit(
                file_name=str(meta.get("source_file") or meta.get("source") or "Документ"),
                file_id=meta.get("file_id") or meta.get("doc_id"),
                page=meta.get("source_page") if meta.get("source_page") is not None else meta.get("page"),
                snippet=text,
            )
        )
    return hits


def build_case_rag_tool(
    *,
    user_id: str,
    case_id: str,
    run_id: str,
    default_file_ids: List[str],
    on_tool_completed: Callable[[], None] | None = None,
) -> Any:
    """Factory: search indexed case documents."""

    @tool(TOOL_NAME, args_schema=CaseRagToolInput)
    async def agent_case_search(
        query: str,
        k: int = 8,
        file_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Поиск по документам дела (RAG). Возвращает релевантные фрагменты с источниками."""
        payload = CaseRagToolInput(query=query, k=k, file_ids=file_ids)
        scope_file_ids = payload.file_ids if payload.file_ids else list(default_file_ids or [])
        k_eff = max(3, min(20, int(payload.k)))

        emit_tool_started(
            TOOL_NAME,
            {
                "query": payload.query[:160],
                "k": k_eff,
                "file_count": len(scope_file_ids),
            },
        )

        db = SessionLocal()
        try:

            def _search() -> List[Any]:
                rag = RAGService()
                return rag.retrieve_context(
                    case_id=case_id,
                    query=payload.query,
                    k=k_eff,
                    retrieval_strategy="multi_query",
                    db=db,
                    use_hybrid=True,
                    file_ids=scope_file_ids or None,
                )

            documents = await run_with_timeout(asyncio.to_thread(_search), label=TOOL_NAME)
            hits = _format_hits(documents)
            output = CaseRagToolOutput(
                status="success" if hits else "empty",
                query=payload.query,
                hit_count=len(hits),
                hits=hits,
            )
            result = output.model_dump()
            emit_tool_completed(
                TOOL_NAME,
                success=bool(hits),
                output_summary=f"{len(hits)} фрагментов по запросу «{payload.query[:80]}»",
            )
            if on_tool_completed is not None:
                on_tool_completed()
            logger.info(
                "agent_case_search completed run_id=%s case_id=%s hits=%s",
                run_id,
                case_id,
                len(hits),
            )
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_NAME, success=False, output_summary=str(exc)[:500])
            logger.error("agent_case_search failed run_id=%s: %s", run_id, exc, exc_info=True)
            raise
        finally:
            db.close()

    return agent_case_search
