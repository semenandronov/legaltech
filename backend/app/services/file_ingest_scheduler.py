"""
Case-scoped file ingest scheduler.

Goals (production ingest):
- Coalesce multiple schedule_case_files_processing() calls for the same case into
  one drain loop (no per-file global serialization).
- Allow limited parallelism across different cases (memory / Yandex quotas).
- Per-case FIFO: while a case is draining, newly uploaded file_ids append to the
  same queue and run in the next inner batch without blocking HTTP.

UI should still prefer one multipart upload with all files; this layer is the
server-side safety net for legacy clients and multi-tab uploads.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Set

from app.config import config

logger = logging.getLogger(__name__)

_global_case_semaphore: asyncio.Semaphore | None = None
_states: Dict[str, "_CaseIngestState"] = {}
_states_guard = asyncio.Lock()


def _max_concurrent_cases() -> int:
    raw = int(getattr(config, "FILE_PROCESSING_MAX_CONCURRENT_CASES", 2) or 2)
    return max(1, min(raw, 8))


def _global_semaphore() -> asyncio.Semaphore:
    global _global_case_semaphore
    if _global_case_semaphore is None:
        _global_case_semaphore = asyncio.Semaphore(_max_concurrent_cases())
    return _global_case_semaphore


@dataclass
class _CaseIngestState:
    pending: Deque[str] = field(default_factory=deque)
    seen: Set[str] = field(default_factory=set)
    drain_task: asyncio.Task | None = None


async def _get_state(case_id: str) -> _CaseIngestState:
    async with _states_guard:
        st = _states.get(case_id)
        if st is None:
            st = _CaseIngestState()
            _states[case_id] = st
        return st


def _enqueue_ids(st: _CaseIngestState, file_ids: List[str]) -> int:
    added = 0
    for fid in file_ids:
        if not fid or fid in st.seen:
            continue
        st.seen.add(fid)
        st.pending.append(fid)
        added += 1
    return added


async def enqueue_case_files(file_ids: List[str], case_id: str) -> None:
    """Schedule files for background ingest (non-blocking)."""
    if not file_ids or not case_id:
        return

    st = await _get_state(case_id)
    added = _enqueue_ids(st, file_ids)
    if added == 0:
        return

    if st.drain_task is None or st.drain_task.done():
        st.drain_task = asyncio.create_task(
            _drain_case(case_id),
            name=f"file-ingest-{case_id[:8]}",
        )

    logger.info(
        "File ingest queued: case=%s added=%s pending=%s",
        case_id,
        added,
        len(st.pending),
    )


async def _drain_case(case_id: str) -> None:
    sem = _global_semaphore()
    await sem.acquire()
    try:
        while True:
            st = await _get_state(case_id)
            batch: List[str] = []
            async with _states_guard:
                while st.pending:
                    batch.append(st.pending.popleft())
            if not batch:
                async with _states_guard:
                    st.drain_task = None
                return

            logger.info(
                "File ingest batch start: case=%s files=%s",
                case_id,
                len(batch),
            )
            await _run_batch(batch, case_id)

            st = await _get_state(case_id)
            async with _states_guard:
                if not st.pending:
                    st.drain_task = None
                    return
    finally:
        sem.release()


async def _run_batch(file_ids: List[str], case_id: str) -> None:
    if config.file_processing_via_worker():
        from app.services.file_processing_enqueue import (
            dispatch_files_to_worker,
            _run_local,
        )

        ok = await dispatch_files_to_worker(file_ids, case_id)
        if not ok:
            logger.warning(
                "Worker dispatch failed for case %s — local fallback for %s file(s)",
                case_id,
                len(file_ids),
            )
            await _run_local(file_ids, case_id)
    else:
        from app.services.file_processing_enqueue import _run_local

        await _run_local(file_ids, case_id)


def reset_scheduler_for_tests() -> None:
    """Clear in-memory scheduler state (tests only)."""
    global _global_case_semaphore
    _global_case_semaphore = None
    _states.clear()
