"""Langfuse generation tracing for LangChain LLM calls (assistant pipeline)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
import functools
import inspect
import logging

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


def _has_langfuse_handler(callbacks: Any) -> bool:
    if not callbacks:
        return False
    if not LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE or LangfuseLangchainCallbackHandler is None:
        return False
    for cb in callbacks:
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
    if not langfuse_enabled() or not LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE:
        return merged

    callbacks = list(merged.get("callbacks") or [])
    if not _has_langfuse_handler(callbacks):
        lf_callbacks = get_langchain_callbacks(tags=tags)
        if lf_callbacks:
            callbacks.extend(lf_callbacks)
            merged["callbacks"] = callbacks

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


class LangfuseInstrumentedLLMWrapper:
    """Inject Langfuse CallbackHandler into LangChain LLM invoke/stream paths."""

    def __init__(self, llm: Any, *, default_tags: Optional[list[str]] = None):
        self._llm = llm
        self._default_tags = list(default_tags or [])

    def _merge_config(self, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return merge_langfuse_into_runnable_config(config, tags=self._default_tags or None)

    def invoke(self, input: Any, config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        return self._llm.invoke(input, config=self._merge_config(config), **kwargs)

    async def ainvoke(self, input: Any, config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        return await self._llm.ainvoke(input, config=self._merge_config(config), **kwargs)

    def stream(self, input: Any, config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        return self._llm.stream(input, config=self._merge_config(config), **kwargs)

    def astream(self, input: Any, config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        return self._llm.astream(input, config=self._merge_config(config), **kwargs)

    def batch(self, inputs: List[Any], config: Optional[Dict[str, Any]] = None, **kwargs: Any):
        return self._llm.batch(inputs, config=self._merge_config(config), **kwargs)

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

    def __or__(self, other: Any):
        from langchain_core.runnables import RunnableSequence

        return RunnableSequence(first=self, last=other)

    def __ror__(self, other: Any):
        from langchain_core.runnables import RunnableSequence

        return RunnableSequence(first=other, last=self)

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
