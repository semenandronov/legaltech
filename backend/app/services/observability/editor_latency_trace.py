"""
Детальная телеметрия латентности чата редактора документа.

Цель: видеть, где теряется время (prep, узлы графа, TTFT LLM, полный стрим, постобработка,
первый токен до клиента). Отдельно фиксируем параметры вызова модели — не только длину ответа.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.config import config
from app.services.observability.langfuse_service import (
    get_active_trace_context,
    normalize_observability_metadata,
    trace_contract_event,
)

logger = logging.getLogger(__name__)


def editor_latency_verbose() -> bool:
    """Подробные логи + SSE latency_debug для редактора."""
    return (getattr(config, "EDITOR_LATENCY_VERBOSE", True))


def profile_llm(llm: Any) -> Dict[str, Any]:
    """Снимок параметров LLM без секретов."""
    out: Dict[str, Any] = {
        "llm_class": type(llm).__name__,
        "api_path": "unknown",
    }
    model = getattr(llm, "model", None) or getattr(llm, "model_name", None)
    if model:
        out["model"] = str(model)[:200]
    out["streaming"] = bool(getattr(llm, "streaming", False))
    for attr in ("max_tokens", "temperature", "timeout"):
        val = getattr(llm, attr, None)
        if val is not None:
            out[attr] = val
    mk = getattr(llm, "model_kwargs", None) or {}
    if isinstance(mk, dict):
        if mk.get("reasoning_effort") is not None:
            out["reasoning_effort"] = mk.get("reasoning_effort")
        if mk.get("max_tokens") is not None and "max_tokens" not in out:
            out["max_tokens"] = mk.get("max_tokens")
    rm = getattr(config, "YANDEX_REASONING_MODE", None)
    re = getattr(config, "YANDEX_REASONING_EFFORT", None)
    if rm:
        out["env_YANDEX_REASONING_MODE"] = str(rm)
    if re:
        out["env_YANDEX_REASONING_EFFORT"] = str(re)
    out["env_LLM_PROVIDER"] = getattr(config, "LLM_PROVIDER", None)
    out["env_YANDEX_GPT_MODEL_URI"] = (getattr(config, "YANDEX_GPT_MODEL_URI", None) or "")[:120]
    cls = out["llm_class"].lower()
    if "yandex" in cls or "openai" in cls:
        out["api_path"] = "yandex_openai_chat_completions"
    elif "gigachat" in cls:
        out["api_path"] = "gigachat"
    return out


def analyze_prompt_payload(
    *,
    system_prompt: str,
    human_payload: str,
    context_parts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Разбивка размера промпта по блокам."""
    parts_meta: List[Dict[str, Any]] = []
    if context_parts:
        for i, part in enumerate(context_parts):
            label = "context"
            head = (part or "")[:80]
            if head.startswith("==="):
                label = head.split("===")[1].strip()[:48] or f"block_{i}"
            parts_meta.append({"label": label, "chars": len(part or "")})
    return {
        "system_chars": len(system_prompt or ""),
        "human_chars": len(human_payload or ""),
        "context_total_chars": sum(p["chars"] for p in parts_meta),
        "context_blocks": parts_meta,
        "estimated_input_chars": len(system_prompt or "") + len(human_payload or ""),
    }


@dataclass
class EditorTurnLatency:
    """Накопитель метрик одного хода редактора."""

    turn_id: Optional[str] = None
    thread_id: Optional[str] = None
    document_id: Optional[str] = None
    editor_mode_hint: Optional[str] = None
    request_started_at: float = field(default_factory=time.monotonic)
    stages: Dict[str, Any] = field(default_factory=dict)
    graph_nodes: List[Dict[str, Any]] = field(default_factory=list)
    llm: Dict[str, Any] = field(default_factory=dict)
    prompt: Dict[str, Any] = field(default_factory=dict)

    def set_stage(self, name: str, **fields: Any) -> None:
        self.stages[name] = {**fields, "recorded_at_ms": self.elapsed_ms()}

    def add_graph_node(
        self,
        node_name: str,
        *,
        since_stream_start_ms: int,
        since_prev_ms: int,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        row = {
            "node": node_name,
            "since_stream_start_ms": since_stream_start_ms,
            "since_prev_ms": since_prev_ms,
        }
        if extra:
            row.update(extra)
        self.graph_nodes.append(row)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.request_started_at) * 1000)

    def merge_llm_metrics(self, data: Dict[str, Any]) -> None:
        self.llm.update(data)

    def to_dict(self) -> Dict[str, Any]:
        total_ms = self.elapsed_ms()
        first_token_client = self.stages.get("first_sse_token_to_client", {}).get("ms")
        llm_ttft = self.llm.get("ttft_ms")
        llm_wall = self.llm.get("stream_wall_ms") or self.llm.get("invoke_wall_ms")
        prep = self.stages.get("prep", {})
        astream = self.stages.get("astream", {})
        notes: List[str] = []
        if llm_ttft is not None and first_token_client is not None:
            gap = int(first_token_client) - int(llm_ttft)
            if gap > 200:
                notes.append(
                    f"Клиент получил первый токен на {gap} ms позже TTFT модели "
                    f"(очередь графа/SSE после generate_response)."
                )
        if llm_wall and llm_ttft:
            gen_after_ttft = int(llm_wall) - int(llm_ttft)
            notes.append(
                f"После первого токена модель ещё ~{gen_after_ttft} ms (длина ответа / скорость стрима); "
                f"это не «ожидание без стрима»."
            )
        return {
            "turn_id": self.turn_id,
            "thread_id": self.thread_id,
            "document_id": self.document_id,
            "editor_mode_hint": self.editor_mode_hint,
            "total_ms": total_ms,
            "stages": self.stages,
            "graph_nodes": self.graph_nodes,
            "llm": self.llm,
            "prompt": self.prompt,
            "notes": notes,
            "prep_ms": prep.get("prep_ms"),
            "graph_compile_ms": prep.get("graph_compile_ms"),
            "checkpoint_load_ms": prep.get("checkpoint_load_ms"),
            "astream_wall_ms": astream.get("astream_wall_ms"),
            "first_sse_token_ms": first_token_client,
            "llm_ttft_ms": llm_ttft,
            "llm_stream_wall_ms": self.llm.get("stream_wall_ms"),
            "llm_invoke_wall_ms": self.llm.get("invoke_wall_ms"),
            "postprocess_ms": self.stages.get("postprocess", {}).get("total_ms"),
        }


def log_editor_turn_summary(latency: EditorTurnLatency) -> None:
    """Структурированный лог для консоли (grep [EditorLatency])."""
    payload = latency.to_dict()
    logger.info(
        "[EditorLatency] turn_summary %s",
        json.dumps(payload, ensure_ascii=False, default=str),
    )


def emit_editor_turn_summary(latency: EditorTurnLatency) -> None:
    """Langfuse contract event + лог."""
    log_editor_turn_summary(latency)
    ctx = get_active_trace_context()
    if not ctx:
        return
    trace_contract_event(
        ctx,
        name="editor_turn_latency_summary",
        metadata=normalize_observability_metadata(
            latency.to_dict(),
            step_name="editor_turn_latency",
            status="success",
            latency_ms=latency.elapsed_ms(),
        ),
    )


def format_latency_debug_sse(latency: EditorTurnLatency) -> str:
    """JSON для SSE type=latency_debug (только при EDITOR_LATENCY_VERBOSE)."""
    import json as _json

    return _json.dumps(
        {"type": "latency_debug", "data": latency.to_dict()},
        ensure_ascii=False,
        default=str,
    )
