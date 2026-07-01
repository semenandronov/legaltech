"""
Сводная временная шкала внутреннего ассистента (case chat).

Собирает latency_ms из вложенных span'ов и в конце запроса:
- пишет структурированный INFO-лог;
- отправляет событие ``pipeline_timeline`` в Langfuse (если включён).

Два роутера (разные роли, см. finalize_case_assistant_timeline docstring):
- ``router.data_plane`` — SQL / RAG / hybrid (structured_data_router);
- ``document_scope_router`` — какие файлы искать в RAG (CaseRouter).
"""
from __future__ import annotations

import logging
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.observability.langfuse_service import (
    get_active_trace_context,
    langfuse_enabled,
    normalize_observability_metadata,
    trace_contract_event,
)

logger = logging.getLogger(__name__)

_timeline_var: ContextVar[Optional["CaseAssistantTimeline"]] = ContextVar(
    "case_assistant_timeline",
    default=None,
)

# Langfuse / log names for the two routers (do not merge — different jobs).
ROUTER_DATA_PLANE = "router.data_plane"
ROUTER_DOCUMENT_SCOPE = "document_scope_router"


@dataclass
class TimelinePhase:
    name: str
    latency_ms: int
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseAssistantTimeline:
    started_at: float = field(default_factory=time.monotonic)
    phases: List[TimelinePhase] = field(default_factory=list)

    def record(self, name: str, latency_ms: int, meta: Optional[Dict[str, Any]] = None) -> None:
        safe_meta = {k: v for k, v in (meta or {}).items() if v is not None}
        self.phases.append(TimelinePhase(name=name, latency_ms=max(0, int(latency_ms)), meta=safe_meta))

    def to_dict(self, *, wall_total_ms: Optional[int] = None) -> Dict[str, Any]:
        recorded = sum(p.latency_ms for p in self.phases)
        return {
            "wall_total_ms": wall_total_ms,
            "recorded_ms": recorded,
            "unattributed_ms": max(0, (wall_total_ms or 0) - recorded) if wall_total_ms else None,
            "phases": [
                {"name": p.name, "latency_ms": p.latency_ms, **p.meta}
                for p in self.phases
            ],
        }


def start_case_assistant_timeline() -> Token:
    return _timeline_var.set(CaseAssistantTimeline())


def reset_case_assistant_timeline(token: Token) -> None:
    _timeline_var.reset(token)


def get_case_assistant_timeline() -> Optional[CaseAssistantTimeline]:
    return _timeline_var.get()


def record_timeline_phase(
    name: str,
    latency_ms: int,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    tl = get_case_assistant_timeline()
    if tl is not None:
        tl.record(name, latency_ms, meta)


def maybe_record_from_span(step_name: str, latency_ms: int, out: Dict[str, Any]) -> None:
    """Hook from assistant_step_span / case_assistant_span."""
    tl = get_case_assistant_timeline()
    if tl is None:
        return
    meta = {k: v for k, v in out.items() if k != "latency_ms"}
    tl.record(step_name, latency_ms, meta)


def finalize_case_assistant_timeline(
    *,
    wall_total_ms: int,
    case_id: str = "",
    data_plane: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Завершить сборку шкалы и опубликовать в лог + Langfuse.

    Пояснение двух роутеров в phases:
    - router.data_plane: нужны ли строки выписки (SQL) или текст документов (RAG).
    - document_scope_router: в каких file_id делать hybrid search (возражение, иск, …).
    """
    tl = get_case_assistant_timeline()
    if tl is None:
        payload = {"wall_total_ms": wall_total_ms, "phases": []}
    else:
        payload = tl.to_dict(wall_total_ms=wall_total_ms)
        if data_plane:
            payload["structured_data_plane"] = data_plane
        if case_id:
            payload["case_id"] = case_id

    phase_lines = []
    for p in payload.get("phases") or []:
        if not isinstance(p, dict):
            continue
        nm = p.get("name", "?")
        ms = p.get("latency_ms", 0)
        extras = {k: v for k, v in p.items() if k not in ("name", "latency_ms")}
        extra_s = f" {extras}" if extras else ""
        phase_lines.append(f"  {nm}: {ms}ms{extra_s}")

    logger.info(
        "[CaseAssistantTimeline] case=%s wall=%sms recorded=%sms\n%s",
        case_id or "?",
        wall_total_ms,
        payload.get("recorded_ms"),
        "\n".join(phase_lines) if phase_lines else "  (no phases)",
    )

    ctx = get_active_trace_context()
    if ctx and langfuse_enabled():
        trace_contract_event(
            ctx,
            name="pipeline_timeline",
            metadata=normalize_observability_metadata(
                {
                    "case_id": case_id,
                    "wall_total_ms": wall_total_ms,
                    "structured_data_plane": data_plane,
                },
                step_name="pipeline_timeline",
                status="success",
                latency_ms=wall_total_ms,
            ),
            output_payload=payload,
        )

    return payload
