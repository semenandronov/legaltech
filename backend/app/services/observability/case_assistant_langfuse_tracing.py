"""
Детальная Langfuse-трассировка внутреннего ассистента по делу (case assistant).

Иерархия (под активным trace запроса):
  case_assistant.pipeline
    ├── case_assistant.router
    ├── case_assistant.file_summary_scope
    ├── case_assistant.hybrid_recall
    │     ├── case_assistant.macro_micro_funnel
    │     │     ├── case_assistant.hybrid.macro | .micro | .scoped_micro | .docling
    │     │     └── (внутри hybrid_search: dense / fts / anchor / bm25 / rrf)
    ├── case_assistant.rerank
    └── case_assistant.assemble_context
          └── case_assistant.fetch_originals

Связанные шаги graph/stream/orchestrator — в assistant_pipeline_langfuse_tracing.
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


def case_assistant_detailed_tracing_enabled() -> bool:
    if not langfuse_enabled():
        return False
    return bool(getattr(config, "CASE_ASSISTANT_LANGFUSE_DETAILED", True))


def _doc_brief(doc: Any) -> Dict[str, Any]:
    meta = getattr(doc, "metadata", None) or {}
    if not isinstance(meta, dict):
        meta = {}
    return {
        "file_id": str(meta.get("file_id") or meta.get("doc_id") or "")[:64],
        "source_file": str(meta.get("source_file") or meta.get("filename") or "")[:120],
        "chunk_level": str(meta.get("chunk_level") or ""),
        "chunk_id": str(meta.get("chunk_id") or "")[:48],
        "combined_score": round(float(meta.get("combined_score") or 0.0), 4)
        if meta.get("combined_score") is not None
        else None,
        "rerank_score": round(float(meta.get("rerank_score") or 0.0), 4)
        if meta.get("rerank_score") is not None
        else None,
    }


def summarize_case_documents(
    docs: Sequence[Any],
    *,
    max_items: int = 12,
) -> Dict[str, Any]:
    items = list(docs or [])
    files: List[str] = []
    seen_files: set[str] = set()
    levels: Dict[str, int] = {}
    for d in items:
        brief = _doc_brief(d)
        fn = brief.get("source_file") or brief.get("file_id") or ""
        if fn and fn not in seen_files:
            seen_files.add(fn)
            files.append(str(fn)[:120])
        lvl = str(brief.get("chunk_level") or "unknown")
        levels[lvl] = levels.get(lvl, 0) + 1
    return {
        "docs_count": len(items),
        "unique_files": len(files),
        "file_names": files[:max_items],
        "chunk_levels": levels,
        "top_docs": [_doc_brief(d) for d in items[:max_items]],
    }


def summarize_metadata_filter(
    metadata_filter: Optional[Dict[str, Any]],
    *,
    file_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    flt = dict(metadata_filter or {})
    if file_ids and "file_id" not in flt:
        flt["file_id"] = file_ids if len(file_ids) != 1 else file_ids[0]
    safe: Dict[str, Any] = {}
    for k, v in flt.items():
        if isinstance(v, (list, tuple, set)):
            safe[k] = list(v)[:20]
        else:
            safe[k] = v
    return safe


@contextmanager
def case_assistant_span(
    step_name: str,
    *,
    input_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """Вложенный span + step_started / step_completed для case assistant."""
    ctx = get_active_trace_context()
    t0 = time.monotonic()
    span = None
    parent_token = None
    out_holder: Dict[str, Any] = {}
    inp = dict(input_payload or {})
    meta_base = dict(metadata or {})
    meta_base["case_assistant_step"] = step_name

    if ctx and case_assistant_detailed_tracing_enabled():
        span = trace_span(
            ctx,
            name=f"case_assistant.{step_name}",
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
        if ctx and case_assistant_detailed_tracing_enabled():
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
def case_assistant_pipeline_trace(
    *,
    case_id: str,
    question: str,
    execution_tier: Optional[str] = None,
    recall_k: Optional[int] = None,
    final_k: Optional[int] = None,
    rerank_enabled: Optional[bool] = None,
) -> Iterator[Dict[str, Any]]:
    """Корневой span пайплайна recall/rerank/assemble."""
    meta = {
        "case_id": case_id,
        "execution_tier": execution_tier,
        "recall_k": recall_k,
        "final_k": final_k,
        "rerank_enabled": rerank_enabled,
    }
    with case_assistant_span(
        "pipeline",
        input_payload={"question": (question or "")[:800]},
        metadata=meta,
    ) as holder:
        yield holder


def trace_router_result(
    *,
    scope_mode: str,
    file_ids: List[str],
    doc_type: Optional[str],
    confidence: float,
    rationale: str,
    search_query: str,
    latency_ms: Optional[int] = None,
) -> None:
    ctx = get_active_trace_context()
    if not ctx or not case_assistant_detailed_tracing_enabled():
        return
    trace_contract_event(
        ctx,
        name="step_completed",
        metadata=normalize_observability_metadata(
            {
                "case_assistant_step": "router",
                "scope_mode": scope_mode,
                "scoped_files_count": len(file_ids),
                "doc_type": doc_type,
                "confidence": confidence,
                "latency_ms": latency_ms,
            },
            step_name="router",
            status="success",
            latency_ms=latency_ms,
        ),
        input_payload={"question": (search_query or "")[:800]},
        output_payload={
            "scope_mode": scope_mode,
            "file_ids": file_ids[:20],
            "doc_type": doc_type,
            "confidence": confidence,
            "rationale": (rationale or "")[:400],
        },
    )
