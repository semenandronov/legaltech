"""Langfuse generation tracing for LangChain LLM calls (assistant pipeline)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Literal, Optional
import functools
import inspect
import logging
import time

from langchain_core.runnables import Runnable, RunnableConfig

from app.services.observability.langfuse_service import (
    LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE,
    LangfuseLangchainCallbackHandler,
    _merge_trace_correlation_metadata,
    _trace_span_base_observation,
    _to_attr_string,
    get_active_trace_context,
    get_langchain_callbacks,
    langfuse_enabled,
    normalize_observability_metadata,
    trace_contract_event,
)

logger = logging.getLogger(__name__)


def _resolve_langfuse_parent_span_id() -> Optional[str]:
    ctx = get_active_trace_context()
    if not ctx:
        return None
    base = _trace_span_base_observation(ctx)
    if base is None:
        return None
    obs_id = getattr(base, "id", None)
    return str(obs_id) if obs_id else None


def _iter_callbacks(callbacks: Any) -> List[Any]:
    if not callbacks:
        return []
    if isinstance(callbacks, (list, tuple)):
        return list(callbacks)
    handlers = getattr(callbacks, "handlers", None)
    if isinstance(handlers, list):
        return handlers
    return [callbacks]


def _has_langfuse_handler(callbacks: Any) -> bool:
    if not callbacks:
        return False
    if not LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE or LangfuseLangchainCallbackHandler is None:
        return False
    for cb in _iter_callbacks(callbacks):
        if isinstance(cb, LangfuseLangchainCallbackHandler):
            return True
    return False


def merge_langfuse_into_runnable_config(
    config: Optional[Dict[str, Any]] = None,
    *,
    tags: Optional[list[str]] = None,
    run_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach Langfuse CallbackHandler + trace metadata to LangChain Runnable config."""
    merged: Dict[str, Any] = dict(config or {})
    if langfuse_enabled() and LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE:
        lf_callbacks = get_langchain_callbacks(tags=tags)
        raw_callbacks = merged.get("callbacks")
        if lf_callbacks and not _has_langfuse_handler(raw_callbacks):
            if raw_callbacks is None:
                merged["callbacks"] = lf_callbacks
            elif isinstance(raw_callbacks, (list, tuple)):
                merged["callbacks"] = list(raw_callbacks) + lf_callbacks
            else:
                for handler in lf_callbacks:
                    if hasattr(raw_callbacks, "add_handler"):
                        raw_callbacks.add_handler(handler)
                merged["callbacks"] = raw_callbacks

    metadata = dict(merged.get("metadata") or {})
    ctx = get_active_trace_context()
    if ctx:
        if ctx.user_id and "langfuse_user_id" not in metadata:
            metadata["langfuse_user_id"] = _to_attr_string(ctx.user_id) or ctx.user_id
        if ctx.session_id and "langfuse_session_id" not in metadata:
            metadata["langfuse_session_id"] = _to_attr_string(ctx.session_id) or ctx.session_id
        if ctx.tags and "langfuse_tags" not in metadata:
            metadata["langfuse_tags"] = list(ctx.tags)
    if tags and "langfuse_tags" not in metadata:
        metadata["langfuse_tags"] = [_to_attr_string(t) or t for t in tags if str(t).strip()]
    if metadata:
        merged["metadata"] = metadata
    if run_name:
        merged["run_name"] = run_name
    return merged


@contextmanager
def observe_generation(
    name: str,
    *,
    model: Optional[str] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    """
    Manual Langfuse generation span under the active assistant trace.
    Use for non-LangChain LLM calls; LangChain paths prefer CallbackHandler via wrapper.
    """
    ctx = get_active_trace_context()
    generation = None
    if ctx and langfuse_enabled():
        base = _trace_span_base_observation(ctx)
        if base is not None:
            try:
                meta = _merge_trace_correlation_metadata(ctx, metadata or {})
                if model:
                    meta["model"] = model
                generation = base.start_observation(
                    name=name,
                    as_type="generation",
                    model=model,
                    input=input_payload,
                    metadata=normalize_observability_metadata(meta, step_name=name, status="running"),
                )
                trace_contract_event(
                    ctx,
                    name="llm_generation",
                    metadata=normalize_observability_metadata(
                        {**meta, "generation_name": name},
                        step_name=name,
                        status="running",
                    ),
                    input_payload=input_payload,
                )
            except Exception:
                logger.debug("observe_generation start failed", exc_info=True)
                generation = None
    exc: Optional[BaseException] = None
    try:
        yield generation
    except BaseException as e:
        exc = e
        raise
    finally:
        if generation is not None:
            try:
                if exc:
                    generation.update(
                        level="ERROR",
                        status_message=str(exc)[:500],
                        output={"status": "error"},
                    )
                else:
                    generation.update(output={"status": "ok"})
                generation.end()
            except Exception:
                logger.debug("observe_generation end failed", exc_info=True)


def observe_llm_generation(
    name: str,
    *,
    model: Optional[str] = None,
    capture_input: bool = True,
):
    """
    Decorator: wrap sync/async LLM helper with a Langfuse generation observation.
    Falls back to no-op when Langfuse is disabled.
    """

    def _decorator(func):
        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def _async_wrapper(*args, **kwargs):
                inp = None
                if capture_input:
                    inp = {
                        "args_preview": repr(args)[:800],
                        "kwargs_keys": sorted(kwargs.keys())[:20],
                    }
                with observe_generation(name, model=model, input_payload=inp):
                    return await func(*args, **kwargs)

            return _async_wrapper

        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            inp = None
            if capture_input:
                inp = {
                    "args_preview": repr(args)[:800],
                    "kwargs_keys": sorted(kwargs.keys())[:20],
                }
            with observe_generation(name, model=model, input_payload=inp):
                return func(*args, **kwargs)

        return _sync_wrapper

    return _decorator


class LangfuseInstrumentedLLMWrapper(Runnable):
    """Inject Langfuse CallbackHandler into LangChain LLM invoke/stream paths."""

    def __init__(self, llm: Any, *, default_tags: Optional[list[str]] = None):
        super().__init__()
        self._llm = llm
        self._default_tags = list(default_tags or [])

    def _merge_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return merge_langfuse_into_runnable_config(config, tags=self._default_tags or None)

    def invoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ):
        merged = self._merge_config(config)
        return self._llm.invoke(input, config=merged, **kwargs)

    async def ainvoke(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ):
        merged = self._merge_config(config)
        return await self._llm.ainvoke(input, config=merged, **kwargs)

    def stream(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ):
        merged = self._merge_config(config)
        return self._llm.stream(input, config=merged, **kwargs)

    def astream(
        self,
        input: Any,
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ):
        merged = self._merge_config(config)
        return self._llm.astream(input, config=merged, **kwargs)

    def batch(
        self,
        inputs: List[Any],
        config: Optional[RunnableConfig] = None,
        **kwargs: Any,
    ):
        merged = self._merge_config(config)
        return self._llm.batch(inputs, config=merged, **kwargs)

    def bind(self, **kwargs: Any):
        bound = self._llm.bind(**kwargs) if hasattr(self._llm, "bind") else self._llm
        return LangfuseInstrumentedLLMWrapper(bound, default_tags=self._default_tags)

    def with_config(self, config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        if hasattr(self._llm, "with_config"):
            configured = self._llm.with_config(config, **kwargs)
            return LangfuseInstrumentedLLMWrapper(configured, default_tags=self._default_tags)
        return self

    def with_structured_output(self, *args: Any, **kwargs: Any):
        structured = self._llm.with_structured_output(*args, **kwargs)
        return LangfuseInstrumentedLLMWrapper(structured, default_tags=self._default_tags)

    def __getattr__(self, name: str):
        return getattr(self._llm, name)

    def __setattr__(self, name: str, value: Any):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._llm, name, value)


def apply_langfuse_llm_instrumentation(llm: Any, *, tags: Optional[list[str]] = None) -> Any:
    """Wrap LLM with Langfuse generation tracing when observability is enabled."""
    if not langfuse_enabled() or not LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE:
        return llm
    if isinstance(llm, LangfuseInstrumentedLLMWrapper):
        return llm
    return LangfuseInstrumentedLLMWrapper(llm, default_tags=tags)


def _resolve_llm_model_name(llm: Any) -> Optional[str]:
    for attr in ("model_name", "model", "model_id"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return None


def _extract_llm_response_text(response: Any) -> str:
    if hasattr(response, "content"):
        content = response.content
        if isinstance(content, str):
            return content
        if content is not None:
            return str(content)
    return str(response or "")


def _extract_llm_usage(response: Any) -> Dict[str, Any]:
    usage: Dict[str, Any] = {}
    meta = getattr(response, "response_metadata", None) or {}
    if isinstance(meta, dict):
        raw = meta.get("token_usage") or meta.get("usage")
        if isinstance(raw, dict):
            usage.update(raw)
    usage_meta = getattr(response, "usage_metadata", None)
    if isinstance(usage_meta, dict):
        usage.update(usage_meta)
    return usage


def _finalize_generation_observation(
    generation: Any,
    *,
    output_text: str,
    wall_ms: int,
    metrics: Dict[str, Any],
    usage: Optional[Dict[str, Any]] = None,
) -> None:
    if generation is None:
        return
    try:
        payload: Dict[str, Any] = {
            "status": "ok",
            "invoke_wall_ms": wall_ms,
            "output_chars": len(output_text or ""),
            **metrics,
        }
        if usage:
            payload["usage"] = usage
        generation.update(
            output=payload,
            metadata=normalize_observability_metadata(
                payload,
                step_name="llm_invoke",
                status="success",
                latency_ms=wall_ms,
            ),
        )
    except Exception:
        logger.debug("finalize_generation_observation failed", exc_info=True)


def traced_sync_llm_invoke(
    llm: Any,
    messages: Any,
    *,
    generation_name: str,
    assistant_step: Optional[str] = None,
    assistant_scope: Literal["case", "global"] = "case",
    metadata: Optional[Dict[str, Any]] = None,
    metrics_out: Optional[Dict[str, Any]] = None,
    input_preview_chars: int = 600,
) -> Any:
    """
    Sync LLM invoke with Langfuse GENERATION + optional assistant step span.
    Records invoke_wall_ms and output_chars for latency debugging.
    """
    from app.services.observability.assistant_pipeline_langfuse_tracing import (
        assistant_step_span,
    )

    model = _resolve_llm_model_name(llm)
    meta = dict(metadata or {})
    if model:
        meta.setdefault("model", model)
    inp = {
        "messages_count": len(messages) if isinstance(messages, list) else None,
        "prompt_preview": str(messages)[:input_preview_chars],
    }

    def _run() -> Any:
        t0 = time.monotonic()
        local_metrics: Dict[str, Any] = {"stream": False}
        with observe_generation(
            generation_name,
            model=model,
            input_payload=inp,
            metadata=meta,
        ) as generation:
            response = llm.invoke(messages)
            wall_ms = int((time.monotonic() - t0) * 1000)
            text = _extract_llm_response_text(response)
            usage = _extract_llm_usage(response)
            local_metrics.update(
                {
                    "invoke_wall_ms": wall_ms,
                    "output_chars": len(text),
                }
            )
            _finalize_generation_observation(
                generation,
                output_text=text,
                wall_ms=wall_ms,
                metrics=local_metrics,
                usage=usage or None,
            )
            if metrics_out is not None:
                metrics_out.update(local_metrics)
            return response

    if assistant_step:
        with assistant_step_span(
            assistant_scope,
            assistant_step,
            input_payload=inp,
            metadata=meta,
        ) as holder:
            response = _run()
            holder.update(
                {
                    "invoke_wall_ms": (metrics_out or {}).get("invoke_wall_ms"),
                    "output_chars": (metrics_out or {}).get("output_chars"),
                }
            )
            return response
    return _run()


def traced_collect_llm_stream_text(
    llm: Any,
    messages: List[Any],
    *,
    generation_name: str,
    assistant_step: Optional[str] = None,
    assistant_scope: Literal["case", "global"] = "case",
    metadata: Optional[Dict[str, Any]] = None,
    metrics_out: Optional[Dict[str, Any]] = None,
    writer: Optional[Callable[[Dict[str, Any]], None]] = None,
    input_preview_chars: int = 600,
) -> str:
    """Buffered or custom-channel LLM stream with GENERATION + assistant step timing."""
    from app.services.chat.llm_streaming import (
        collect_llm_stream_text,
        collect_llm_stream_text_with_writer,
    )
    from app.services.observability.assistant_pipeline_langfuse_tracing import (
        assistant_step_span,
    )

    model = _resolve_llm_model_name(llm)
    meta = dict(metadata or {})
    if model:
        meta.setdefault("model", model)
    inp = {
        "messages_count": len(messages),
        "prompt_preview": str(messages)[:input_preview_chars],
        "stream_to_client": writer is not None,
    }

    def _run() -> str:
        stream_metrics: Dict[str, Any] = {}
        t0 = time.monotonic()
        with observe_generation(
            generation_name,
            model=model,
            input_payload=inp,
            metadata=meta,
        ) as generation:
            if writer is not None:
                text = collect_llm_stream_text_with_writer(
                    llm,
                    messages,
                    writer,
                    metrics_out=stream_metrics,
                )
            else:
                text = collect_llm_stream_text(
                    llm,
                    messages,
                    metrics_out=stream_metrics,
                )
            wall_ms = int((time.monotonic() - t0) * 1000)
            stream_metrics.setdefault("stream_wall_ms", wall_ms)
            _finalize_generation_observation(
                generation,
                output_text=text,
                wall_ms=wall_ms,
                metrics=stream_metrics,
            )
            if metrics_out is not None:
                metrics_out.update(stream_metrics)
            return text

    if assistant_step:
        with assistant_step_span(
            assistant_scope,
            assistant_step,
            input_payload=inp,
            metadata=meta,
        ) as holder:
            text = _run()
            holder.update(
                {
                    "stream_wall_ms": (metrics_out or {}).get("stream_wall_ms"),
                    "ttft_ms": (metrics_out or {}).get("ttft_ms"),
                    "output_chars": len(text or ""),
                    "chunk_count": (metrics_out or {}).get("chunk_count"),
                }
            )
            return text
    return _run()
