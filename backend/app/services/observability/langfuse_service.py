"""Langfuse observability integration with safe fallbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, List
import logging
import uuid
import time
from contextvars import ContextVar
import httpx
import re
import json
import functools
import inspect

from app.config import config

logger = logging.getLogger(__name__)
_TRACE_ID_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
OBSERVABILITY_EVENT_NAMES = {
    "request_received",
    "request_routed",
    "prompt_prepared",
    "llm_generation",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
    "quality_gate",
    "response_saved",
    "request_completed",
    "step_started",
    "step_completed",
    "step_failed",
    "sla_warning",
    "graph_node_completed",
}


try:
    from langfuse import Langfuse, propagate_attributes, observe  # type: ignore

    LANGFUSE_SDK_AVAILABLE = True
    LANGFUSE_OBSERVE_AVAILABLE = True
except Exception:
    Langfuse = None  # type: ignore
    LANGFUSE_SDK_AVAILABLE = False
    LANGFUSE_OBSERVE_AVAILABLE = False

try:
    from langfuse.langchain import CallbackHandler as LangfuseLangchainCallbackHandler  # type: ignore

    LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE = True
except Exception:
    LangfuseLangchainCallbackHandler = None  # type: ignore
    LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE = False


@dataclass
class TraceContext:
    """Runtime trace context for one request/flow."""

    trace_id: str
    started_at: float
    name: str
    metadata: Dict[str, Any]
    root_observation: Optional[Any] = None
    _attrs_scope: Optional[Any] = None
    _root_scope: Optional[Any] = None

    @property
    def elapsed_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)


_client: Optional[Any] = None
_init_done = False
_active_trace_ctx: ContextVar[Optional[TraceContext]] = ContextVar("active_langfuse_trace_ctx", default=None)
# When set, trace_span() nests new observations under this parent (e.g. case_chat_route_to_handler).
_trace_span_parent: ContextVar[Optional[Any]] = ContextVar("langfuse_trace_span_parent", default=None)
_MAX_TEXT_LEN = 4000
_MAX_COLLECTION_ITEMS = 50
_ATTR_VALUE_MAX_LEN = 200
_SENSITIVE_KEY_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie)", re.IGNORECASE)
_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")


def _truncate_text(value: str, max_len: int = _MAX_TEXT_LEN) -> str:
    if len(value) <= max_len:
        return value
    return f"{value[:max_len]}...<truncated:{len(value) - max_len}>"


def _safe_json_value(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "<max_depth_reached>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, bytes):
        return _truncate_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, dict):
        safe_dict: Dict[str, Any] = {}
        for idx, (k, v) in enumerate(value.items()):
            if idx >= _MAX_COLLECTION_ITEMS:
                safe_dict["__truncated_items__"] = f"{len(value) - _MAX_COLLECTION_ITEMS} more"
                break
            safe_key = _truncate_text(str(k), 120)
            if _SENSITIVE_KEY_RE.search(safe_key):
                safe_dict[safe_key] = "<redacted>"
            else:
                safe_dict[safe_key] = _safe_json_value(v, depth + 1)
        return safe_dict
    if isinstance(value, (list, tuple, set)):
        items = list(value)
        safe_items = [_safe_json_value(v, depth + 1) for v in items[:_MAX_COLLECTION_ITEMS]]
        if len(items) > _MAX_COLLECTION_ITEMS:
            safe_items.append(f"<truncated_items:{len(items) - _MAX_COLLECTION_ITEMS}>")
        return safe_items
    return _truncate_text(repr(value))


def _safe_mapping(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    return _safe_json_value(payload)  # type: ignore[return-value]


def _safe_attribute_mapping(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    OTel attributes should be flat scalar-ish values.
    Convert nested objects to compact JSON strings.
    """
    safe_payload = _safe_mapping(payload)
    if not safe_payload:
        return None
    attrs: Dict[str, Any] = {}
    for key, value in safe_payload.items():
        if value is None or isinstance(value, (bool, int, float, str)):
            attrs[key] = value
            continue
        try:
            attrs[key] = _truncate_text(json.dumps(value, ensure_ascii=False))
        except Exception:
            attrs[key] = _truncate_text(repr(value))
    return attrs


def _safe_event_payload(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Preserve nested JSON-safe payload for Langfuse event input/output/metadata.
    Flattening to scalar strings reduces debugging value for complex agent traces.
    """
    return _safe_mapping(payload)


def _merge_event_input_with_metadata(
    safe_input: Optional[Dict[str, Any]],
    safe_metadata: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Langfuse UI/exports can differ by SDK/version in how event metadata is surfaced.
    Mirror metadata into input payload to keep critical observability context visible.
    """
    if not safe_metadata:
        return safe_input
    if not safe_input:
        return {"event_metadata": safe_metadata}
    merged = dict(safe_input)
    if "event_metadata" not in merged:
        merged["event_metadata"] = safe_metadata
    return merged


def _normalize_attr_key(key: Any) -> Optional[str]:
    raw = _truncate_text(str(key), 120)
    normalized = _ALNUM_RE.sub("", raw)
    if not normalized:
        return None
    return normalized[:80]


def _to_attr_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(_safe_json_value(value), ensure_ascii=False)
        except Exception:
            text = repr(value)
    text = _truncate_text(text, _ATTR_VALUE_MAX_LEN).strip()
    if not text:
        return None
    return text


def _safe_propagated_metadata(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    safe_payload = _safe_mapping(payload)
    if not safe_payload:
        return None
    result: Dict[str, str] = {}
    for key, value in safe_payload.items():
        normalized_key = _normalize_attr_key(key)
        if not normalized_key:
            continue
        if _SENSITIVE_KEY_RE.search(normalized_key):
            result[normalized_key] = "<redacted>"
            continue
        text_value = _to_attr_string(value)
        if text_value is None:
            continue
        result[normalized_key] = text_value
    return result or None


def _safe_propagated_tags(tags: Optional[list[str]]) -> Optional[list[str]]:
    if not tags:
        return None
    result: list[str] = []
    for tag in tags:
        text_value = _to_attr_string(tag)
        if text_value is None:
            continue
        result.append(text_value)
    if not result:
        return None
    return result[:_MAX_COLLECTION_ITEMS]


def langfuse_enabled() -> bool:
    return bool(
        getattr(config, "LANGFUSE_ENABLED", False)
        and getattr(config, "LANGFUSE_PUBLIC_KEY", "")
        and getattr(config, "LANGFUSE_SECRET_KEY", "")
    )


def init_langfuse() -> bool:
    """Initialize singleton Langfuse client."""
    global _client, _init_done
    if _init_done:
        return _client is not None
    _init_done = True

    if not LANGFUSE_SDK_AVAILABLE:
        logger.info("Langfuse SDK not installed, running without tracing")
        return False
    if not langfuse_enabled():
        logger.info("Langfuse disabled by config or missing keys")
        return False

    try:
        _client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
            debug=bool(getattr(config, "LANGFUSE_DEBUG", False)),
        )
        logger.info(
            "Langfuse initialized: host=%s debug=%s",
            config.LANGFUSE_HOST,
            bool(getattr(config, "LANGFUSE_DEBUG", False)),
        )
        return True
    except Exception as exc:
        logger.warning("Langfuse initialization failed: %s", exc, exc_info=True)
        _client = None
        return False


def get_langfuse_client() -> Optional[Any]:
    if not _init_done:
        init_langfuse()
    return _client


def create_trace_context(
    *,
    name: str,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> TraceContext:
    trace_id_value = normalize_trace_id(trace_id)
    payload = dict(metadata or {})
    safe_metadata = _safe_event_payload(payload)
    safe_attrs_metadata = _safe_propagated_metadata(payload)
    safe_input_payload = _safe_event_payload(input_payload)
    safe_input_payload = _merge_event_input_with_metadata(safe_input_payload, safe_metadata)
    safe_user_id = _to_attr_string(user_id)
    safe_session_id = _to_attr_string(session_id)
    safe_trace_name = _to_attr_string(name) or "assistant_trace"
    safe_tags = _safe_propagated_tags(tags)
    client = get_langfuse_client()
    root_observation = None
    attrs_scope = None
    root_scope = None
    if client is not None:
        try:
            # Langfuse Python SDK v4 uses observation-centric API.
            # We create a root span observation and attach a fixed trace_id via trace_context.
            attrs_scope = propagate_attributes(
                trace_name=safe_trace_name,
                user_id=safe_user_id,
                session_id=safe_session_id,
                metadata=safe_attrs_metadata,
                tags=safe_tags,
            )
            attrs_scope.__enter__()
            root_scope = client.start_as_current_observation(
                trace_context={"trace_id": trace_id_value},
                as_type="span",
                name=name,
                input=safe_input_payload,
                metadata=safe_metadata,
            )
            root_observation = root_scope.__enter__()
            # Ensure root span always has canonical payload, even if SDK internals
            # omit attributes passed at start in some versions.
            if root_observation is not None:
                root_observation.update(
                    input=safe_input_payload,
                    metadata=safe_metadata,
                )
        except Exception as exc:
            logger.warning("Langfuse trace creation failed: %s", exc, exc_info=True)
            root_observation = None
            if attrs_scope is not None:
                try:
                    attrs_scope.__exit__(None, None, None)
                except Exception:
                    logger.debug("Langfuse propagate_attributes cleanup failed", exc_info=True)
            attrs_scope = None
            if root_scope is not None:
                try:
                    root_scope.__exit__(None, None, None)
                except Exception:
                    logger.debug("Langfuse root observation cleanup failed", exc_info=True)
            root_scope = None

    return TraceContext(
        trace_id=trace_id_value,
        started_at=time.time(),
        name=name,
        metadata=safe_metadata or {},
        root_observation=root_observation,
        _attrs_scope=attrs_scope,
        _root_scope=root_scope,
    )


def trace_event(
    ctx: Optional[TraceContext] = None,
    *,
    name: str,
    level: str = "DEFAULT",
    metadata: Optional[Dict[str, Any]] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    output_payload: Optional[Dict[str, Any]] = None,
) -> None:
    ctx = ctx or _active_trace_ctx.get()
    if not ctx:
        return
    safe_metadata = _safe_event_payload(metadata)
    safe_input = _safe_event_payload(input_payload)
    safe_input = _merge_event_input_with_metadata(safe_input, safe_metadata)
    safe_output = _safe_event_payload(output_payload)
    try:
        event_level = level if level in {"DEBUG", "DEFAULT", "WARNING", "ERROR"} else "DEFAULT"
        # Prefer observation-native events to keep parent chain and payload stable.
        if ctx.root_observation is not None:
            event_observation = ctx.root_observation.create_event(
                name=name,
                metadata=safe_metadata,
                input=safe_input,
                output=safe_output,
                level=event_level,
            )
            return

        client = get_langfuse_client()
        if client is None:
            return
        client.create_event(
            name=name,
            trace_context={"trace_id": ctx.trace_id},
            level=event_level,
            metadata=safe_metadata,
            input=safe_input,
            output=safe_output,
        )
    except Exception as exc:
        logger.warning("Langfuse event failed: %s (%s)", name, exc)


def trace_span(
    ctx: Optional[TraceContext] = None,
    *,
    name: str,
    metadata: Optional[Dict[str, Any]] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    output_payload: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    ctx = ctx or _active_trace_ctx.get()
    if not ctx:
        return None
    base = _trace_span_base_observation(ctx)
    if not base:
        return None
    try:
        return base.start_observation(
            name=name,
            as_type="span",
            metadata=_safe_event_payload(metadata),
            input=_safe_event_payload(input_payload),
            output=_safe_event_payload(output_payload),
        )
    except Exception:
        logger.debug("Langfuse span failed", exc_info=True)
        return None


def update_trace(
    ctx: Optional[TraceContext] = None,
    *,
    output_payload: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    ctx = ctx or _active_trace_ctx.get()
    if not ctx or not ctx.root_observation:
        return
    try:
        merged = dict(ctx.metadata)
        if metadata:
            merged.update(metadata)
            ctx.metadata = _safe_event_payload(merged) or {}
        safe_output = _safe_event_payload(output_payload)
        safe_metadata = _safe_event_payload(merged)
        ctx.root_observation.update(
            output=safe_output,
            metadata=safe_metadata,
        )
    except Exception:
        logger.debug("Langfuse trace update failed", exc_info=True)


def end_trace(
    ctx: Optional[TraceContext] = None,
    *,
    status: str,
    output_payload: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    ctx = ctx or _active_trace_ctx.get()
    if not ctx:
        return
    merged = dict(metadata or {})
    merged["status"] = status
    merged["duration_ms"] = ctx.elapsed_ms
    if error:
        merged["error"] = error
    try:
        update_trace(ctx, output_payload=output_payload, metadata=merged)
    finally:
        if ctx._root_scope is not None:
            try:
                ctx._root_scope.__exit__(None, None, None)
            except Exception:
                logger.debug("Langfuse root scope exit failed", exc_info=True)
            finally:
                ctx._root_scope = None
                ctx.root_observation = None
        elif ctx.root_observation is not None:
            # Compatibility path when root scope is not available.
            try:
                ctx.root_observation.end()
            except Exception:
                logger.debug("Langfuse trace end failed", exc_info=True)
            finally:
                ctx.root_observation = None

        if ctx._attrs_scope is not None:
            try:
                ctx._attrs_scope.__exit__(None, None, None)
            except Exception:
                logger.debug("Langfuse propagate_attributes exit failed", exc_info=True)
            finally:
                ctx._attrs_scope = None

        if bool(getattr(config, "LANGFUSE_FLUSH_ON_END", True)):
            flush_langfuse()


def record_score(
    *,
    trace_id: str,
    name: str,
    value: float,
    comment: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    client = get_langfuse_client()
    if client is None:
        return False
    try:
        client.create_score(
            trace_id=trace_id,
            name=name,
            value=value,
            comment=comment,
            metadata=metadata or None,
        )
        return True
    except Exception:
        logger.debug("Langfuse score failed", exc_info=True)
        return False


def get_prompt_text(
    *,
    prompt_name: str,
    fallback: str,
    variables: Optional[Dict[str, Any]] = None,
    label: Optional[str] = None,
    version: Optional[int] = None,
) -> str:
    client = get_langfuse_client()
    if client is None:
        return fallback

    try:
        prompt = client.get_prompt(
            prompt_name,
            label=label,
            version=version,
        )
        if hasattr(prompt, "compile"):
            return str(prompt.compile(**(variables or {})))
        content = getattr(prompt, "prompt", None) or getattr(prompt, "text", None)
        if isinstance(content, str) and content.strip():
            return content
    except Exception:
        logger.debug("Langfuse prompt fetch failed for %s", prompt_name, exc_info=True)
    return fallback


def flush_langfuse() -> None:
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception:
        logger.debug("Langfuse flush failed", exc_info=True)


def get_langchain_callbacks(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> List[Any]:
    """
    Build LangChain callbacks list with Langfuse CallbackHandler when available.
    Returns an empty list when Langfuse is disabled/unavailable.
    """
    if not langfuse_enabled() or not LANGFUSE_LANGCHAIN_HANDLER_AVAILABLE:
        return []
    try:
        handler_kwargs: Dict[str, Any] = {}
        safe_session_id = _to_attr_string(session_id)
        safe_user_id = _to_attr_string(user_id)
        safe_tags = _safe_propagated_tags(tags)
        if safe_session_id:
            handler_kwargs["session_id"] = safe_session_id
        if safe_user_id:
            handler_kwargs["user_id"] = safe_user_id
        if safe_tags:
            handler_kwargs["tags"] = safe_tags
        return [LangfuseLangchainCallbackHandler(**handler_kwargs)]
    except Exception:
        logger.debug("Langfuse CallbackHandler init failed", exc_info=True)
        return []


def check_langfuse_auth_health(timeout_sec: float = 5.0) -> tuple[bool, str]:
    """
    Validate Langfuse credentials against Public API without exposing secrets.

    Returns:
        (ok, message)
    """
    if not langfuse_enabled():
        return False, "disabled_or_missing_keys"

    host = (getattr(config, "LANGFUSE_HOST", "") or "").strip().rstrip("/")
    public_key = (getattr(config, "LANGFUSE_PUBLIC_KEY", "") or "").strip()
    secret_key = (getattr(config, "LANGFUSE_SECRET_KEY", "") or "").strip()
    if not host:
        return False, "missing_host"

    url = f"{host}/api/public/projects"
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            response = client.get(url, auth=(public_key, secret_key))
        if response.status_code == 200:
            return True, "ok"
        if response.status_code in (401, 403):
            return False, f"auth_failed_status_{response.status_code}"
        return False, f"unexpected_status_{response.status_code}"
    except Exception as exc:
        return False, f"request_error_{type(exc).__name__}"


def set_active_trace_context(ctx: Optional[TraceContext]):
    """Bind trace context to current coroutine context."""
    return _active_trace_ctx.set(ctx)


def reset_active_trace_context(token) -> None:
    """Reset previously bound coroutine trace context."""
    _active_trace_ctx.reset(token)


def get_active_trace_context() -> Optional[TraceContext]:
    return _active_trace_ctx.get()


def set_trace_span_parent(observation: Optional[Any]):
    """
    Make subsequent trace_span() calls attach under this observation (until reset).
    Pass None to nest under the trace root again.
    Returns a token for reset_trace_span_parent().
    """
    return _trace_span_parent.set(observation)


def reset_trace_span_parent(token) -> None:
    """Undo set_trace_span_parent()."""
    try:
        _trace_span_parent.reset(token)
    except Exception:
        logger.debug("trace_span_parent reset failed", exc_info=True)


def _trace_span_base_observation(ctx: TraceContext) -> Optional[Any]:
    parent = _trace_span_parent.get()
    if parent is not None:
        return parent
    return ctx.root_observation


def normalize_trace_id(trace_id: Optional[str]) -> str:
    """Normalize trace id to Langfuse v4-compatible 32-char lowercase hex."""
    raw_trace_id = (trace_id or "").strip().lower().replace("-", "")
    if _TRACE_ID_HEX_RE.fullmatch(raw_trace_id):
        return raw_trace_id
    if raw_trace_id:
        logger.warning("Invalid trace_id format received; generating a new one")
    return uuid.uuid4().hex


def build_assistant_trace_metadata(
    *,
    feature: str,
    route: str,
    environment: Optional[str],
    model_provider: Optional[str],
    case_id: Optional[str] = None,
    draft_mode: Optional[bool] = None,
    draft_approved: Optional[bool] = None,
    attached_files_count: Optional[int] = None,
    web_search: Optional[bool] = None,
    legal_research: Optional[bool] = None,
    deep_think: Optional[bool] = None,
    assistant_type: Optional[str] = None,
    mode: Optional[str] = None,
    execution_path: Optional[str] = None,
    scope_result: Optional[str] = None,
    citation_result: Optional[str] = None,
    confidence_result: Optional[str] = None,
    tags: Optional[list[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Canonical metadata contract for assistant traces.
    """
    metadata: Dict[str, Any] = {
        "feature": feature,
        "route": route,
        "environment": environment or "development",
        "model_provider": model_provider or "unknown",
    }
    if case_id:
        metadata["case_id"] = case_id
    if draft_mode is not None:
        metadata["draft_mode"] = bool(draft_mode)
    if draft_approved is not None:
        metadata["draft_approved"] = bool(draft_approved)
    if attached_files_count is not None:
        metadata["attached_files_count"] = int(attached_files_count)
    if assistant_type:
        metadata["assistant_type"] = assistant_type
    if mode:
        metadata["mode"] = mode
    if execution_path:
        metadata["execution_path"] = execution_path
    if scope_result:
        metadata["scope_result"] = scope_result
    if citation_result:
        metadata["citation_result"] = citation_result
    if confidence_result:
        metadata["confidence_result"] = confidence_result
    metadata["tooling_flags"] = {
        "web_search": bool(web_search) if web_search is not None else False,
        "legal_research": bool(legal_research) if legal_research is not None else False,
        "deep_think": bool(deep_think) if deep_think is not None else False,
    }
    if extra:
        metadata.update(extra)
    if tags:
        metadata["tags"] = [str(t) for t in tags if str(t).strip()]
    return metadata


def normalize_observability_metadata(
    metadata: Optional[Dict[str, Any]] = None,
    *,
    step_name: Optional[str] = None,
    status: Optional[str] = None,
    latency_ms: Optional[int] = None,
    citations_count: Optional[int] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Normalized metadata contract for assistant observability events/spans.
    """
    merged: Dict[str, Any] = dict(metadata or {})
    if step_name:
        merged["step_name"] = step_name
    if status:
        merged["status"] = status
    if latency_ms is not None:
        merged["latency_ms"] = int(latency_ms)
    if citations_count is not None:
        merged["citations_count"] = int(citations_count)
    if error:
        merged["error"] = error
    return merged


def trace_contract_event(
    ctx: Optional[TraceContext] = None,
    *,
    name: str,
    level: str = "DEFAULT",
    metadata: Optional[Dict[str, Any]] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    output_payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emit a normalized observability event for assistant flows.
    """
    event_name = name if name in OBSERVABILITY_EVENT_NAMES else name
    trace_event(
        ctx,
        name=event_name,
        level=level,
        metadata=metadata,
        input_payload=input_payload,
        output_payload=output_payload,
    )


def start_trace_attribute_scope(
    *,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[list[str]] = None,
):
    """
    Start a nested propagate_attributes scope for current active trace context.
    Useful when session_id becomes known later in request lifecycle.
    """
    scope = propagate_attributes(
        session_id=_to_attr_string(session_id),
        user_id=_to_attr_string(user_id),
        metadata=_safe_propagated_metadata(metadata),
        tags=_safe_propagated_tags(tags),
    )
    scope.__enter__()
    return scope


def observe_span(name: str):
    """
    Safe Langfuse @observe wrapper for span instrumentation.
    Falls back to no-op decorator when SDK/decorator is unavailable.
    """
    def _decorator(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def _async_wrapper(*args, **kwargs):
                span = trace_span(
                    name=name,
                    metadata={"decorated_function": getattr(func, "__qualname__", func.__name__)},
                )
                try:
                    result = await func(*args, **kwargs)
                    if span:
                        span.update(output={"status": "ok"})
                    return result
                except Exception as exc:
                    if span:
                        span.update(level="ERROR", status_message=str(exc), output={"status": "error"})
                    raise
                finally:
                    if span:
                        try:
                            span.end()
                        except Exception:
                            logger.debug("Langfuse observe span end failed", exc_info=True)

            return _async_wrapper

        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs):
            span = trace_span(
                name=name,
                metadata={"decorated_function": getattr(func, "__qualname__", func.__name__)},
            )
            try:
                result = func(*args, **kwargs)
                if span:
                    span.update(output={"status": "ok"})
                return result
            except Exception as exc:
                if span:
                    span.update(level="ERROR", status_message=str(exc), output={"status": "error"})
                raise
            finally:
                if span:
                    try:
                        span.end()
                    except Exception:
                        logger.debug("Langfuse observe span end failed", exc_info=True)

        return _sync_wrapper

    return _decorator
