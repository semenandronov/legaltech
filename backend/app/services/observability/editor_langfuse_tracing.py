"""
Подробная Langfuse-трассировка чата текстового редактора (Ask / Edit / Draft).
"""
from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from app.config import config
from app.services.observability.langfuse_service import (
    build_assistant_trace_metadata,
    get_active_trace_context,
    normalize_observability_metadata,
    reset_trace_span_parent,
    set_trace_span_parent,
    trace_contract_event,
    trace_span,
)


def should_sample_langfuse() -> bool:
    sample_rate = float(getattr(config, "LANGFUSE_SAMPLE_RATE", 1.0) or 1.0)
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    return random.random() <= sample_rate


def build_editor_trace_metadata(
    *,
    case_id: str,
    document_id: str,
    editor_mode_hint: str,
    user_id: str,
    session_id: Optional[str] = None,
    legal_research: bool = False,
    deep_think: bool = False,
    has_selection: bool = False,
    attached_files_count: int = 0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    hint = (editor_mode_hint or "ask").strip().lower()
    return build_assistant_trace_metadata(
        feature="document_editor",
        route="/api/documents-editor/{document_id}/chat/stream",
        environment=getattr(config, "ENVIRONMENT", None),
        model_provider=getattr(config, "LLM_PROVIDER", None),
        case_id=case_id,
        legal_research=legal_research,
        deep_think=deep_think,
        assistant_type="document_editor",
        mode=hint,
        execution_path=f"editor_langgraph_{hint}",
        tags=[
            "assistant",
            "document_editor",
            f"editor_{hint}",
        ],
        attached_files_count=attached_files_count,
        extra={
            "document_id": document_id,
            "editor_mode_hint": hint,
            "has_selection": has_selection,
            **(extra or {}),
        },
    )


def editor_state_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Безопасный снимок state для Langfuse (без HTML целиком)."""
    msgs = list(state.get("messages") or [])
    doc = (state.get("document_context") or "")
    sel = (state.get("selected_text") or "")
    rag = (state.get("rag_context") or "")
    meta = state.get("context_pipeline_meta") if isinstance(state.get("context_pipeline_meta"), dict) else {}
    edits = state.get("structured_edits") or []
    return {
        "case_id": state.get("case_id"),
        "document_id": state.get("document_id"),
        "editor_mode_hint": state.get("editor_mode_hint"),
        "question_preview": (state.get("question") or "")[:500],
        "messages_count": len(msgs),
        "document_context_chars": len(doc),
        "selected_text_chars": len(sel),
        "rag_context_chars": len(rag),
        "citations_count": len(state.get("citations") or []),
        "structured_edits_count": len(edits) if isinstance(edits, list) else 0,
        "edits_valid": state.get("edits_valid"),
        "edit_iterations": state.get("edit_iterations"),
        "edit_validation_iteration": state.get("edit_validation_iteration"),
        "checkpoint_has_response": bool((state.get("response") or "").strip()),
        "context_pipeline": meta,
        "attached_file_ids_count": len(state.get("attached_file_ids") or []),
    }


def editor_node_output_summary(node_name: str, result: Any) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"node": node_name, "result_type": type(result).__name__}
    out = {"node": node_name}
    if "structured_edits" in result:
        se = result.get("structured_edits") or []
        out["structured_edits_count"] = len(se) if isinstance(se, list) else 0
        if isinstance(se, list) and se:
            out["first_edit_preview"] = {
                "has_node_id": bool(se[0].get("node_id")),
                "original_len": len(str(se[0].get("original_text") or "")),
                "new_len": len(str(se[0].get("new_text") or "")),
                "found": se[0].get("found_in_document"),
            }
    if "response" in result and result.get("response"):
        out["response_chars"] = len(str(result.get("response") or ""))
    if "edits_valid" in result:
        out["edits_valid"] = result.get("edits_valid")
    if "edit_errors" in result:
        errs = result.get("edit_errors") or []
        out["edit_errors_count"] = len(errs) if isinstance(errs, list) else 0
    if "changes_applied" in result:
        out["changes_applied"] = result.get("changes_applied")
    if "edited_content" in result and result.get("edited_content"):
        out["edited_content_chars"] = len(str(result.get("edited_content") or ""))
    if "context_pipeline_meta" in result:
        out["context_pipeline_meta"] = result.get("context_pipeline_meta")
    if "rag_context" in result and result.get("rag_context"):
        out["rag_context_chars"] = len(str(result.get("rag_context") or ""))
    if "errors" in result and result.get("errors"):
        out["errors_count"] = len(result.get("errors") or [])
    return out


def enrich_editor_graph_node_metadata(
    node_name: str,
    node_data: Dict[str, Any],
    *,
    editor_mode_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """Доп. поля для graph_node_completed в режиме редактора."""
    meta: Dict[str, Any] = {
        "graph_node": node_name,
        "editor_mode_hint": editor_mode_hint,
    }
    if node_name == "editor_enrich_context":
        cpm = node_data.get("context_pipeline_meta") or {}
        if isinstance(cpm, dict):
            meta.update(
                {
                    "pipeline": cpm.get("pipeline"),
                    "recall_docs": cpm.get("recall_docs"),
                    "rerank_docs": cpm.get("rerank_docs"),
                    "scope_mode": cpm.get("scope_mode"),
                }
            )
        meta["rag_context_chars"] = len(str(node_data.get("rag_context") or ""))
        meta["citations_count"] = len(node_data.get("citations") or [])
    elif node_name == "generate_edits":
        se = node_data.get("structured_edits") or []
        meta["structured_edits_count"] = len(se) if isinstance(se, list) else 0
    elif node_name == "validate_edits":
        meta["edits_valid"] = node_data.get("edits_valid")
        meta["edit_validation_iteration"] = node_data.get("edit_validation_iteration")
    elif node_name == "apply_edits":
        meta["changes_applied"] = node_data.get("changes_applied")
    elif node_name == "generate_response":
        meta["response_chars"] = len(str(node_data.get("response") or ""))
        meta["citations_count"] = len(node_data.get("citations") or [])
        elm = node_data.get("editor_latency_meta")
        if isinstance(elm, dict):
            flat = dict(elm)
            llm_sub = elm.get("llm")
            if isinstance(llm_sub, dict):
                flat.update(llm_sub)
                llm_prof = llm_sub.get("llm_profile")
                if isinstance(llm_prof, dict):
                    flat.update(llm_prof)
            prompt_sub = elm.get("prompt")
            if isinstance(prompt_sub, dict):
                flat.update(prompt_sub)
            for key in (
                "ttft_ms",
                "stream_wall_ms",
                "invoke_wall_ms",
                "postprocess_ms",
                "system_chars",
                "context_total_chars",
                "estimated_input_chars",
                "api_path",
                "model",
                "reasoning_effort",
                "max_tokens",
                "chunk_count",
                "output_chars",
            ):
                if key in flat:
                    meta[key] = flat[key]
    elif node_name == "generate_editor_snippet":
        meta["snippet_chars"] = len(str(node_data.get("response") or ""))
    return meta


def trace_editor_route_decision(state: Dict[str, Any], target_node: str) -> None:
    ctx = get_active_trace_context()
    if not ctx:
        return
    trace_contract_event(
        ctx,
        name="request_routed",
        metadata=normalize_observability_metadata(
            {
                **editor_state_summary(state),
                "target_node": target_node,
                "routing": "editor_mode_hint",
            },
            step_name="editor_route",
            status="success",
        ),
        input_payload={"question": (state.get("question") or "")[:800]},
        output_payload={"target_node": target_node},
    )


@contextmanager
def editor_node_trace(
    state: Dict[str, Any],
    node_name: str,
    *,
    extra_input: Optional[Dict[str, Any]] = None,
) -> Iterator[Optional[Any]]:
    """
    Вложенный span узла редактора + step_started / step_completed.
    Внутри with — set_trace_span_parent для LLM CallbackHandler.
    """
    ctx = get_active_trace_context()
    t0 = time.monotonic()
    span = None
    parent_token = None
    inp = editor_state_summary(state)
    if extra_input:
        inp.update(extra_input)
    if ctx:
        span = trace_span(
            ctx,
            name=f"editor.node.{node_name}",
            metadata=normalize_observability_metadata(
                {**inp, "step_name": node_name},
                step_name=node_name,
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
                inp,
                step_name=node_name,
                status="started",
            ),
            input_payload={"question": (state.get("question") or "")[:800]},
        )
    exc: Optional[BaseException] = None
    output_holder: Dict[str, Any] = {}
    try:

        class _TraceSink:
            def set_output(self, result: Any) -> None:
                output_holder["data"] = editor_node_output_summary(node_name, result)

        yield _TraceSink() if ctx else None
    except BaseException as e:
        exc = e
        raise
    finally:
        wall_ms = int((time.monotonic() - t0) * 1000)
        if parent_token is not None:
            reset_trace_span_parent(parent_token)
        if ctx:
            status = "error" if exc else "success"
            out = output_holder.get("data") or {}
            if exc:
                out["error"] = str(exc)[:500]
            trace_contract_event(
                ctx,
                name="step_failed" if exc else "step_completed",
                metadata=normalize_observability_metadata(
                    {**inp, **out},
                    step_name=node_name,
                    status=status,
                    latency_ms=wall_ms,
                    error=str(exc)[:500] if exc else None,
                ),
                output_payload=out,
            )
        if span is not None:
            try:
                span.update(
                    output=output_holder.get("data"),
                    metadata=normalize_observability_metadata(
                        inp,
                        step_name=node_name,
                        status="error" if exc else "success",
                        latency_ms=wall_ms,
                    ),
                )
                span.end()
            except Exception:
                pass
