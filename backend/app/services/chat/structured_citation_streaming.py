"""Stream structured citations to LangGraph custom channel (text + citations)."""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import BaseMessage

from app.services.chat.llm_streaming import StreamWriter
from app.services.chat.structured_citations_core import (
    ChunkCitationStreamTransformer,
    StructuredCitationPrepareResult,
    iter_transformed_llm_stream,
    map_structured_answer_text,
)
from app.services.langchain_agents.schemas.citation_schema import EnhancedCitation

CitationEnricher = Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]


def collect_structured_citation_stream(
    llm: Any,
    prepare: StructuredCitationPrepareResult,
    writer: StreamWriter,
    *,
    enrich_citations: Optional[CitationEnricher] = None,
    metrics_out: Optional[Dict[str, Any]] = None,
) -> tuple[str, List[EnhancedCitation]]:
    """
    Stream LLM answer with [CHUNK:...] transformed to [N] on the fly.

    Emits:
      - ``text_delta`` for user-visible text
      - ``citations`` with monotonically growing enriched payload (if enricher provided)

    Returns:
        (final_user_answer, raw_enhanced_citations before final enrich pass)
    """
    transformer = ChunkCitationStreamTransformer(chunk_map=dict(prepare.chunk_map))
    t0 = time.monotonic()
    ttft_ms: Optional[int] = None
    chunk_count = 0
    raw_citations: List[EnhancedCitation] = []
    user_parts: List[str] = []

    for user_text, new_citations in iter_transformed_llm_stream(
        llm, list(prepare.messages), transformer
    ):
        if user_text:
            chunk_count += 1
            if ttft_ms is None:
                ttft_ms = int((time.monotonic() - t0) * 1000)
            user_parts.append(user_text)
            writer({"type": "text_delta", "textDelta": user_text})

        if new_citations:
            raw_citations.extend(new_citations)
            if enrich_citations is not None:
                dumped = [c.model_dump() for c in raw_citations]
                enriched = enrich_citations(dumped)
                if enriched:
                    writer({"type": "citations", "citations": enriched})

    user_answer = "".join(user_parts)

    # Final normalization on complete raw model output (fallback [N] paths, whitespace).
    raw_model = transformer.raw_accumulated
    if raw_model.strip():
        mapped, mapped_citations = map_structured_answer_text(
            raw_model,
            prepare.chunk_map,
            num_chunks=prepare.num_chunks,
            chunk_ids_list=prepare.chunk_ids_list,
        )
        if mapped_citations:
            raw_citations = mapped_citations
        # If mapping adjusted text vs streamed (rare), sync via content_sync downstream.
        user_answer = mapped

    if enrich_citations is not None and raw_citations:
        enriched = enrich_citations([c.model_dump() for c in raw_citations])
        if enriched:
            writer({"type": "citations", "citations": enriched})

    if metrics_out is not None:
        wall_ms = int((time.monotonic() - t0) * 1000)
        metrics_out.update(
            {
                "stream": True,
                "ttft_ms": ttft_ms if ttft_ms is not None else wall_ms,
                "stream_wall_ms": wall_ms,
                "chunk_count": chunk_count,
                "output_chars": len(user_answer),
                "raw_output_chars": len(raw_model),
            }
        )

    return user_answer, raw_citations
