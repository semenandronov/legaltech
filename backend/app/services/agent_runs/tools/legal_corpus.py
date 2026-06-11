"""Legal corpus (нормативная база) search tool for deep agents."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import tool

from app.services.agent_runs.schemas import LegalCorpusHit, LegalCorpusToolInput, LegalCorpusToolOutput
from app.services.agent_runs.tools._helpers import (
    emit_tool_completed,
    emit_tool_started,
    run_with_timeout,
)
from app.services.legal_corpus_service import retrieve_legal_corpus_documents

logger = logging.getLogger(__name__)

TOOL_NAME = "agent_legal_corpus_search"
MAX_SNIPPET_CHARS = 1000


def _format_legal_hits(documents: List[Any]) -> List[LegalCorpusHit]:
    hits: List[LegalCorpusHit] = []
    for doc in documents:
        meta = doc.metadata or {}
        text = (doc.page_content or "").strip()
        if not text:
            continue
        if len(text) > MAX_SNIPPET_CHARS:
            text = text[:MAX_SNIPPET_CHARS] + "…"
        hits.append(
            LegalCorpusHit(
                source_filename=str(meta.get("source_filename") or meta.get("title") or "норма"),
                instrument_id=meta.get("instrument_id"),
                section_title=meta.get("section_title"),
                snippet=text,
            )
        )
    return hits


def build_legal_corpus_tool(
    *,
    run_id: str,
    on_tool_completed: Callable[[], None] | None = None,
) -> Any:
    """Factory: search global legal corpus."""

    @tool(TOOL_NAME, args_schema=LegalCorpusToolInput)
    async def agent_legal_corpus_search(
        query: str,
        k: int = 6,
        instrument_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Поиск в правовом справочнике (кодексы, законы, разъяснения)."""
        payload = LegalCorpusToolInput(query=query, k=k, instrument_ids=instrument_ids)
        k_eff = max(2, min(12, int(payload.k)))

        emit_tool_started(
            TOOL_NAME,
            {"query": payload.query[:160], "k": k_eff},
        )

        try:

            def _search() -> List[Any]:
                return retrieve_legal_corpus_documents(
                    payload.query,
                    k=k_eff,
                    instrument_ids=payload.instrument_ids,
                    final_k=k_eff,
                )

            documents = await run_with_timeout(asyncio.to_thread(_search), label=TOOL_NAME)
            hits = _format_legal_hits(documents)
            output = LegalCorpusToolOutput(
                status="success" if hits else "empty",
                query=payload.query,
                hit_count=len(hits),
                hits=hits,
            )
            result = output.model_dump()
            emit_tool_completed(
                TOOL_NAME,
                success=bool(hits),
                output_summary=f"{len(hits)} норм по запросу «{payload.query[:80]}»",
            )
            if on_tool_completed is not None:
                on_tool_completed()
            logger.info(
                "agent_legal_corpus_search completed run_id=%s hits=%s",
                run_id,
                len(hits),
            )
            return result
        except Exception as exc:
            emit_tool_completed(TOOL_NAME, success=False, output_summary=str(exc)[:500])
            logger.error("agent_legal_corpus_search failed run_id=%s: %s", run_id, exc, exc_info=True)
            raise

    return agent_legal_corpus_search
