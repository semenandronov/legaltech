"""
Пошаговая Langfuse-трассировка пайплайна ассистента (case + global).

Иерархия (под trace запроса):
  assistant.{scope}.{step}
    case: http.*, orchestrator.*, session_context.*, graph_prepare.*, persist.*
    global: http.*, orchestrator.*, session_context.*, langgraph.*, generation.*, persist.*

    graph.generate.build_prompt
    graph.generate.structured_citations
      ├── structured_citations.prepare_chunks
      ├── structured_citations.llm_invoke   (Langfuse GENERATION)
      └── structured_citations.map_citations
    graph.generate.llm_stream               (Langfuse GENERATION, default path)
    graph.generate.postprocess
  stream.finalize_response
  stream.emit_finish
  orchestrator.prepare_session
  orchestrator.save_assistant_message

Включение: ASSISTANT_PIPELINE_LANGFUSE_DETAILED или CASE_ASSISTANT_LANGFUSE_DETAILED.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Literal, Optional

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

AssistantScope = Literal["case", "global"]


def assistant_pipeline_tracing_enabled() -> bool:
    if not langfuse_enabled():
        return False
    if bool(getattr(config, "ASSISTANT_PIPELINE_LANGFUSE_DETAILED", True)):
        return True
    return bool(getattr(config, "CASE_ASSISTANT_LANGFUSE_DETAILED", True))


@contextmanager
def assistant_step_span(
    scope: AssistantScope,
    step_name: str,
    *,
    input_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Iterator[Dict[str, Any]]:
    """Вложенный span + step_started / step_completed для любого шага ассистента."""
    ctx = get_active_trace_context()
    t0 = time.monotonic()
    span = None
    parent_token = None
    out_holder: Dict[str, Any] = {}
    inp = dict(input_payload or {})
    meta_base = dict(metadata or {})
    meta_base["assistant_scope"] = scope
    meta_base["assistant_step"] = step_name
    full_name = f"assistant.{scope}.{step_name}"

    if ctx and assistant_pipeline_tracing_enabled():
        span = trace_span(
            ctx,
            name=full_name,
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
        if ctx and assistant_pipeline_tracing_enabled():
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


def turn_context_trace_fields(turn_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact turn-context slice for trace metadata (no large payloads)."""
    if not isinstance(turn_context, dict):
        return {}
    return {
        "referential_kind": str(turn_context.get("referential_kind") or "none"),
        "needs_document_retrieval": bool(turn_context.get("needs_document_retrieval", True)),
        "routing_resolver": str(turn_context.get("routing_resolver") or ""),
        "query_resolver": str(turn_context.get("query_resolver") or ""),
        "suggested_intent": str(turn_context.get("suggested_intent") or ""),
        "confidence": float(turn_context.get("confidence") or 0.0),
    }


def record_execution_branch(
    scope: AssistantScope,
    *,
    branch: str,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record which high-level path handled the turn (visible in Langfuse timeline)."""
    ctx = get_active_trace_context()
    if not ctx or not assistant_pipeline_tracing_enabled():
        return
    meta = dict(metadata or {})
    meta["assistant_scope"] = scope
    meta["execution_branch"] = branch
    if reason:
        meta["branch_reason"] = reason
    trace_contract_event(
        ctx,
        name="execution_branch",
        metadata=normalize_observability_metadata(
            meta,
            step_name=f"{scope}.{branch}",
            status="success",
        ),
        output_payload={"branch": branch, "reason": reason},
    )


def _graph_node_output_payload(node_data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    resp = node_data.get("response")
    if isinstance(resp, str):
        out["response_chars"] = len(resp)
    cites = node_data.get("citations")
    if isinstance(cites, list):
        out["citations_count"] = len(cites)
    for key in (
        "execution_tier",
        "legal_intent",
        "grade_retrieval_ok",
        "retrieval_round",
        "escalated_from",
    ):
        if key in node_data and node_data.get(key) is not None:
            out[key] = node_data.get(key)
    rag_docs = node_data.get("rag_documents")
    if isinstance(rag_docs, list):
        out["rag_docs_count"] = len(rag_docs)
    rag_ctx = node_data.get("rag_context")
    if isinstance(rag_ctx, str) and rag_ctx.strip():
        out["rag_context_chars"] = len(rag_ctx)
    errs = node_data.get("errors")
    if isinstance(errs, list) and errs:
        out["errors_count"] = len(errs)
        out["errors_preview"] = [str(e)[:160] for e in errs[:3]]
    return out


def record_graph_node_completed(
    scope: AssistantScope,
    *,
    node_name: str,
    node_data: Dict[str, Any],
    since_stream_start_ms: int,
    since_prev_graph_update_ms: int,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Span + event per LangGraph node update (case/global assistant stream)."""
    ctx = get_active_trace_context()
    if not ctx or not assistant_pipeline_tracing_enabled():
        return
    output_payload = _graph_node_output_payload(node_data)
    meta: Dict[str, Any] = {
        "assistant_scope": scope,
        "graph_node": str(node_name),
        "since_stream_start_ms": since_stream_start_ms,
        "since_prev_graph_update_ms": since_prev_graph_update_ms,
        "state_keys_preview": list(node_data.keys())[:25],
        **output_payload,
    }
    if extra:
        meta.update(extra)
    span = trace_span(
        ctx,
        name=f"assistant.{scope}.graph.{node_name}",
        metadata=normalize_observability_metadata(
            meta,
            step_name=f"graph.{node_name}",
            status="success",
        ),
        input_payload={"node": node_name},
    )
    if span is not None:
        try:
            span.update(output=output_payload)
            span.end()
        except Exception:
            pass
    trace_contract_event(
        ctx,
        name="graph_node_completed",
        metadata=normalize_observability_metadata(
            meta,
            step_name="graph_node_completed",
            status="success",
        ),
        output_payload=output_payload,
    )


def record_assistant_step(
    scope: AssistantScope,
    step_name: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    output_payload: Optional[Dict[str, Any]] = None,
    latency_ms: Optional[int] = None,
) -> None:
    """Мгновенное событие шага (без context manager)."""
    ctx = get_active_trace_context()
    if not ctx or not assistant_pipeline_tracing_enabled():
        return
    meta = dict(metadata or {})
    meta["assistant_scope"] = scope
    meta["assistant_step"] = step_name
    trace_contract_event(
        ctx,
        name="step_completed",
        metadata=normalize_observability_metadata(
            meta,
            step_name=step_name,
            status="success",
            latency_ms=latency_ms,
        ),
        output_payload=output_payload or {},
    )
