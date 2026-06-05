"""
Детальная Langfuse-трассировка подбора судебной практики (court_practice).

Иерархия (под активным trace запроса):
  court_practice.pipeline
    ├── court_practice.query_planner
    ├── court_practice.embed_query
    ├── court_practice.hybrid_search
    ├── court_practice.fts_supplement
    ├── court_practice.rerank
    └── court_practice.finalize
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence

from app.config import config
from app.services.observability.langfuse_service import (
    get_active_trace_context,
    langfuse_enabled,
    normalize_observability_metadata,
    reset_trace_span_parent,
    set_trace_span_parent,
    trace_contract_event,
    trace_span,
)


def court_practice_detailed_tracing_enabled() -> bool:
    if not langfuse_enabled():
        return False
    return bool(getattr(config, "COURT_PRACTICE_LANGFUSE_DETAILED", True))


def _hit_brief(hit: Any) -> Dict[str, Any]:
    return {
        "chunk_id": str(getattr(hit, "chunk_id", "") or "")[:64],
        "case_number": str(getattr(hit, "case_number", "") or "")[:64],
        "court_tier": str(getattr(hit, "court_tier", "") or ""),
        "court_name": (str(getattr(hit, "court_name", "") or ""))[:120],
        "score": round(float(getattr(hit, "score", 0.0) or 0.0), 4),
        "dense_rank": getattr(hit, "dense_rank", None),
        "sparse_rank": getattr(hit, "sparse_rank", None),
    }


def summarize_hits(
    hits: Sequence[Any],
    *,
    max_items: int = 12,
) -> Dict[str, Any]:
    items = list(hits or [])
    cases: List[str] = []
    seen_cases: set[str] = set()
    for h in items:
        cn = str(getattr(h, "case_number", "") or "").strip()
        if cn and cn not in seen_cases:
            seen_cases.add(cn)
            cases.append(cn)
    return {
        "hits_count": len(items),
        "unique_cases": len(cases),
        "case_numbers": cases[: max_items],
        "top_hits": [_hit_brief(h) for h in items[:max_items]],
    }


def summarize_documents(docs: Sequence[Any], *, max_items: int = 8) -> Dict[str, Any]:
    items = list(docs or [])
    cases: List[str] = []
    seen: set[str] = set()
    for d in items:
        meta = getattr(d, "metadata", None) or {}
        if not isinstance(meta, dict):
            meta = {}
        cn = str(meta.get("case_number") or meta.get("file_name") or "").strip()
        if cn and cn not in seen:
            seen.add(cn)
            cases.append(cn[:80])
    return {
        "documents_count": len(items),
        "unique_cases": len(cases),
        "case_numbers": cases[:max_items],
    }


@contextmanager
def court_practice_span(
    step_name: str,
    *,
    input_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """
    Вложенный span + step_started / step_completed.
    Yields mutable dict для накопления output (ключи merge в finally).
    """
    ctx = get_active_trace_context()
    t0 = time.monotonic()
    span = None
    parent_token = None
    out_holder: Dict[str, Any] = {}
    inp = dict(input_payload or {})
    meta_base = dict(metadata or {})
    meta_base["court_practice_step"] = step_name

    if ctx and court_practice_detailed_tracing_enabled():
        span = trace_span(
            ctx,
            name=f"court_practice.{step_name}",
            metadata=normalize_observability_metadata(
                meta_base,
                step_name=step_name,
                status="running",
            ),
            input_payload=inp,
        )
        if span is not None:
            parent_token = set_trace_span_parent(span)
        trace_contract_event(
            ctx,
            name="step_started",
            metadata=normalize_observability_metadata(
                meta_base,
                step_name=step_name,
                status="started",
            ),
            input_payload=inp,
        )

    exc: Optional[BaseException] = None
    try:
        yield out_holder
    except BaseException as e:
        exc = e
        raise
    finally:
        wall_ms = int((time.monotonic() - t0) * 1000)
        if parent_token is not None:
            reset_trace_span_parent(parent_token)
        if ctx and court_practice_detailed_tracing_enabled():
            merged_out = {**out_holder, "latency_ms": wall_ms}
            status = "error" if exc else "success"
            trace_contract_event(
                ctx,
                name="step_failed" if exc else "step_completed",
                metadata=normalize_observability_metadata(
                    {**meta_base, **merged_out},
                    step_name=step_name,
                    status=status,
                    latency_ms=wall_ms,
                    error=str(exc)[:500] if exc else None,
                ),
                output_payload=merged_out,
            )
            if span is not None:
                try:
                    span.update(
                        output=merged_out,
                        metadata=normalize_observability_metadata(
                            {**meta_base, **merged_out},
                            step_name=step_name,
                            status=status,
                            latency_ms=wall_ms,
                        ),
                    )
                    span.end()
                except Exception:
                    pass


@contextmanager
def court_practice_pipeline_trace(
    *,
    query: str,
    search_queries: Optional[List[str]] = None,
    final_k: Optional[int] = None,
    use_reranker: Optional[bool] = None,
    source: str = "retrieve",
    case_id: Optional[str] = None,
) -> Iterator[Dict[str, Any]]:
    """Корневой span всего пайплайна retrieval."""
    meta = {
        "source": source,
        "final_k": final_k,
        "use_reranker": use_reranker,
        "search_queries_count": len(search_queries or []),
        "case_id": case_id,
    }
    with court_practice_span(
        "pipeline",
        input_payload={
            "query": (query or "")[:800],
            "search_queries": list(search_queries or [])[:12],
        },
        metadata=meta,
    ) as holder:
        yield holder


def trace_planner_result(
    *,
    question: str,
    search_queries: List[str],
    planner_source: str,
    rationale: str = "",
    latency_ms: Optional[int] = None,
) -> None:
    ctx = get_active_trace_context()
    if not ctx or not court_practice_detailed_tracing_enabled():
        return
    trace_contract_event(
        ctx,
        name="step_completed",
        metadata=normalize_observability_metadata(
            {
                "court_practice_step": "query_planner",
                "planner_source": planner_source,
                "search_queries_count": len(search_queries),
                "latency_ms": latency_ms,
            },
            step_name="query_planner",
            status="success",
            latency_ms=latency_ms,
        ),
        input_payload={"question": (question or "")[:800]},
        output_payload={
            "search_queries": search_queries[:12],
            "planner_source": planner_source,
            "rationale": (rationale or "")[:300],
        },
    )
