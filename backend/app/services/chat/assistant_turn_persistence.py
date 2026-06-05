"""Фоновая персистенция ответов ассистента (case + global).

HTTP/SSE поток не ждёт commit в БД: после finish клиенту ставится задача
с отдельной SQLAlchemy-сессией и ограниченным retry.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import config
from app.services.chat.evidence_bundle import build_evidence_bundle
from app.services.chat.history_service import ChatHistoryService
from app.services.chat.session_context_service import refresh_session_context_after_turn
from app.services.observability.langfuse_service import (
    get_active_trace_context,
    trace_contract_event,
    trace_event,
    normalize_observability_metadata,
)

logger = logging.getLogger(__name__)

_PERSIST_RETRY_DELAYS_SEC = (0.35, 1.0)


@dataclass(frozen=True)
class CaseAssistantPersistJob:
    message_id: str
    case_id: str
    session_id: str
    content: str
    source_references: Optional[Any] = None
    evidence: Optional[Any] = None
    last_user: str = ""
    last_assistant: str = ""


@dataclass(frozen=True)
class GlobalAssistantPersistJob:
    session_id: str
    content: str
    citations: Optional[List[Dict[str, Any]]] = None
    last_user: str = ""
    last_assistant: str = ""


def assistant_async_persist_enabled() -> bool:
    return bool(getattr(config, "ASSISTANT_ASYNC_PERSIST_ENABLED", True))


def persist_writethrough_buffer_enabled() -> bool:
    from app.services.chat.session_turn_buffer import (
        persist_writethrough_buffer_enabled as _buffer_enabled,
    )

    return _buffer_enabled()


def should_sync_persist_before_finish() -> bool:
    """Session memory reads assistant rows from DB unless write-through buffer is active."""
    from app.services.chat.session_context_service import session_context_enabled

    if not session_context_enabled():
        return False
    if (
        persist_writethrough_buffer_enabled()
        and assistant_async_persist_enabled()
    ):
        return False
    return True


def schedule_case_assistant_persist(job: CaseAssistantPersistJob) -> None:
    """Fire-and-forget: не блокирует SSE."""
    if persist_writethrough_buffer_enabled():
        from app.services.chat.session_turn_buffer import buffer_assistant_turn

        buffer_assistant_turn(
            scope="case",
            case_id=job.case_id,
            session_id=job.session_id,
            message_id=job.message_id,
            content=job.content,
            evidence=job.evidence,
        )
    if not assistant_async_persist_enabled():
        _persist_case_sync(job)
        return
    asyncio.create_task(_persist_case_with_retry(job))


def schedule_global_assistant_persist(job: GlobalAssistantPersistJob) -> None:
    if not assistant_async_persist_enabled():
        _persist_global_sync(job)
        return
    asyncio.create_task(_persist_global_with_retry(job))


def persist_case_assistant_sync(job: CaseAssistantPersistJob) -> bool:
    """Синхронный путь (тесты, ASSISTANT_ASYNC_PERSIST_ENABLED=false)."""
    return _persist_case_sync(job)


def persist_global_assistant_sync(job: GlobalAssistantPersistJob) -> bool:
    return _persist_global_sync(job)


async def _persist_case_with_retry(job: CaseAssistantPersistJob) -> None:
    max_retries = max(0, int(getattr(config, "ASSISTANT_ASYNC_PERSIST_MAX_RETRIES", 2) or 2))
    attempts = 1 + max_retries
    last_err: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            ok = await asyncio.to_thread(_persist_case_sync, job)
            if ok:
                _trace_persist_success(
                    assistant_type="case_assistant",
                    session_id=job.session_id,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    content_chars=len(job.content or ""),
                    attempt=attempt,
                )
                return
            last_err = RuntimeError("assistant message not found")
        except Exception as exc:
            last_err = exc
            logger.warning(
                "case assistant async persist attempt %s/%s failed: %s",
                attempt,
                attempts,
                exc,
                exc_info=attempt == attempts,
            )
        if attempt < attempts:
            delay = _PERSIST_RETRY_DELAYS_SEC[min(attempt - 1, len(_PERSIST_RETRY_DELAYS_SEC) - 1)]
            await asyncio.sleep(delay)
    _trace_persist_failure(
        assistant_type="case_assistant",
        session_id=job.session_id,
        error=str(last_err or "unknown"),
    )


async def _persist_global_with_retry(job: GlobalAssistantPersistJob) -> None:
    max_retries = max(0, int(getattr(config, "ASSISTANT_ASYNC_PERSIST_MAX_RETRIES", 2) or 2))
    attempts = 1 + max_retries
    last_err: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            ok = await asyncio.to_thread(_persist_global_sync, job)
            if ok:
                _trace_persist_success(
                    assistant_type="global_assistant",
                    session_id=job.session_id,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    content_chars=len(job.content or ""),
                    attempt=attempt,
                )
                return
            last_err = RuntimeError("global assistant persist returned false")
        except Exception as exc:
            last_err = exc
            logger.warning(
                "global assistant async persist attempt %s/%s failed: %s",
                attempt,
                attempts,
                exc,
                exc_info=attempt == attempts,
            )
        if attempt < attempts:
            delay = _PERSIST_RETRY_DELAYS_SEC[min(attempt - 1, len(_PERSIST_RETRY_DELAYS_SEC) - 1)]
            await asyncio.sleep(delay)
    _trace_persist_failure(
        assistant_type="global_assistant",
        session_id=job.session_id,
        error=str(last_err or "unknown"),
    )


def _persist_case_sync(job: CaseAssistantPersistJob) -> bool:
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        history = ChatHistoryService(db)
        evidence = job.evidence
        if evidence is None and job.source_references:
            citations = job.source_references
            if isinstance(citations, dict):
                citations = citations.get("citations") or []
            if isinstance(citations, list):
                evidence = build_evidence_bundle(citations=citations)
        ok = history.update_assistant_message(
            message_id=job.message_id,
            content=job.content,
            source_references=job.source_references,
            evidence=evidence,
        )
        if ok:
            refresh_session_context_after_turn(
                db,
                scope="case",
                session_id=job.session_id,
                case_id=job.case_id,
                last_user=job.last_user,
                last_assistant=job.last_assistant,
            )
            if persist_writethrough_buffer_enabled():
                from app.services.chat.session_turn_buffer import clear_buffered_turn

                clear_buffered_turn(
                    scope="case",
                    case_id=job.case_id,
                    session_id=job.session_id,
                    message_id=job.message_id,
                )
        return ok
    finally:
        db.close()


def _persist_global_sync(job: GlobalAssistantPersistJob) -> bool:
    import json

    from app.models.case import GlobalAssistantMessage, GlobalAssistantSession
    from app.utils.database import SessionLocal

    db = SessionLocal()
    try:
        citations = list(job.citations or [])
        evidence_bundle = build_evidence_bundle(citations=citations)
        asst_msg = GlobalAssistantMessage(
            session_id=job.session_id,
            role="assistant",
            content=job.content,
            reasoning_steps=[
                {
                    "phase": "citations",
                    "step": 1,
                    "totalSteps": 1,
                    "content": json.dumps(citations, ensure_ascii=False),
                }
            ]
            if citations
            else None,
            evidence=evidence_bundle,
        )
        db.add(asst_msg)
        db.query(GlobalAssistantSession).filter(
            GlobalAssistantSession.id == job.session_id
        ).update({"updated_at": datetime.utcnow()})
        db.commit()
        refresh_session_context_after_turn(
            db,
            scope="global",
            session_id=job.session_id,
            last_user=job.last_user,
            last_assistant=job.last_assistant,
        )
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _trace_persist_success(
    *,
    assistant_type: str,
    session_id: str,
    latency_ms: int,
    content_chars: int,
    attempt: int,
) -> None:
    trace_contract_event(
        get_active_trace_context(),
        name="response_saved",
        metadata=normalize_observability_metadata(
            {
                "assistant_type": assistant_type,
                "session_id": session_id,
                "persist_mode": "async",
                "attempt": attempt,
            },
            step_name="save_assistant_message",
            status="success",
            latency_ms=latency_ms,
        ),
        output_payload={"content_chars": content_chars},
    )


def _trace_persist_failure(*, assistant_type: str, session_id: str, error: str) -> None:
    trace_event(
        get_active_trace_context(),
        name=f"{assistant_type}_async_save_failed",
        level="ERROR",
        metadata={"session_id": session_id, "persist_mode": "async", "error": error},
    )
    logger.error(
        "[%s] async persist failed after retries session=%s: %s",
        assistant_type,
        session_id,
        error,
    )
