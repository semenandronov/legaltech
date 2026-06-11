"""BM25 prewarm для дел: индекс всегда в процессе API, источник — PGVector."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Dict, Optional

from app.config import config

if TYPE_CHECKING:
    from app.services.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)

_case_locks: Dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_prewarm_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bm25-prewarm")
_inflight: Dict[str, bool] = {}
_inflight_guard = threading.Lock()
_pending_force: Dict[str, bool] = {}
_debounce_timers: Dict[str, threading.Timer] = {}
_debounce_lock = threading.Lock()


def _case_lock(case_id: str) -> threading.Lock:
    with _locks_guard:
        if case_id not in _case_locks:
            _case_locks[case_id] = threading.Lock()
        return _case_locks[case_id]


def _bm25_enabled() -> bool:
    return bool(getattr(config, "CASE_BM25_PREWARM_ENABLED", True))


def _debounce_sec() -> float:
    return max(0.0, float(getattr(config, "CASE_BM25_DEBOUNCE_SEC", 1.5) or 1.5))


def _max_chunks() -> int:
    return max(100, int(getattr(config, "CASE_BM25_MAX_CHUNKS", 2500) or 2500))


def ensure_bm25_index(
    document_processor: "DocumentProcessor",
    case_id: str,
    *,
    force_rebuild: bool = False,
) -> bool:
    """
    Гарантирует in-memory BM25 для дела в текущем процессе.

    Чанки загружаются из PGVector (тот же источник, что и hybrid search).
    """
    cid = str(case_id or "").strip()
    if not cid or not _bm25_enabled():
        return False
    if not document_processor.bm25_retriever.available:
        return False
    if document_processor.bm25_retriever.has_index(cid) and not force_rebuild:
        return True

    with _case_lock(cid):
        if document_processor.bm25_retriever.has_index(cid) and not force_rebuild:
            return True
        return bool(document_processor.prewarm_bm25_from_store(cid, force_rebuild=force_rebuild))


def cancel_pending_bm25_prewarm(case_id: str) -> None:
    """Отменить отложенный debounced rebuild (перед синхронным finalize после batch)."""
    cid = str(case_id or "").strip()
    if not cid:
        return
    with _debounce_lock:
        timer = _debounce_timers.pop(cid, None)
        if timer is not None:
            timer.cancel()
        _pending_force.pop(cid, None)


def _submit_bm25_job(case_id: str, *, force_rebuild: bool) -> None:
    cid = str(case_id or "").strip()
    if not cid or not _bm25_enabled():
        return

    with _inflight_guard:
        if _inflight.get(cid):
            if force_rebuild:
                _pending_force[cid] = True
            return
        _inflight[cid] = True

    def _run() -> None:
        rerun_force = False
        try:
            from app.services.document_processor import get_document_processor

            dp = get_document_processor()
            t0 = time.monotonic()
            ok = ensure_bm25_index(dp, cid, force_rebuild=force_rebuild)
            ms = int((time.monotonic() - t0) * 1000)
            if ok:
                logger.info("BM25 background prewarm ok case=%s ms=%s", cid, ms)
            else:
                logger.info("BM25 background prewarm skipped case=%s ms=%s", cid, ms)
        except Exception as exc:
            logger.warning("BM25 background prewarm failed case=%s: %s", cid, exc, exc_info=True)
        finally:
            with _inflight_guard:
                _inflight.pop(cid, None)
                rerun_force = bool(_pending_force.pop(cid, False))

        if rerun_force:
            _submit_bm25_job(cid, force_rebuild=True)

    _prewarm_pool.submit(_run)


def prepare_bm25_for_tabular_extraction(
    document_processor: "DocumentProcessor",
    case_id: str,
) -> bool:
    """
    Ensure BM25 is ready for tabular hybrid search without blocking the HTTP request.

    Schedules background prewarm when the in-memory index is missing; returns whether
    the index is already available in this process.
    """
    cid = str(case_id or "").strip()
    if not cid or not _bm25_enabled():
        return False
    if not document_processor.bm25_retriever.available:
        return False
    if document_processor.bm25_retriever.has_index(cid):
        return True
    schedule_bm25_prewarm(cid)
    return False


def schedule_bm25_prewarm(case_id: str, *, force_rebuild: bool = False) -> None:
    """Фоновый prewarm с debounce: серия store не запускает N параллельных rebuild."""
    cid = str(case_id or "").strip()
    if not cid or not _bm25_enabled():
        return

    debounce = _debounce_sec()
    if debounce <= 0:
        _submit_bm25_job(cid, force_rebuild=force_rebuild)
        return

    with _debounce_lock:
        if force_rebuild:
            _pending_force[cid] = True
        existing = _debounce_timers.get(cid)
        if existing is not None:
            existing.cancel()

        def _fire() -> None:
            with _debounce_lock:
                _debounce_timers.pop(cid, None)
                merged_force = bool(_pending_force.pop(cid, False))
            _submit_bm25_job(cid, force_rebuild=merged_force)

        timer = threading.Timer(debounce, _fire)
        timer.daemon = True
        _debounce_timers[cid] = timer
        timer.start()


def finalize_case_bm25_after_ingestion(
    case_id: str,
    document_processor: Optional["DocumentProcessor"] = None,
) -> bool:
    """
    Один авторитетный rebuild после batch-обработки файлов (источник — PGVector).

    Отменяет debounced jobs и строит индекс синхронно в worker-потоке.
    """
    cid = str(case_id or "").strip()
    if not cid or not _bm25_enabled():
        return False

    cancel_pending_bm25_prewarm(cid)

    try:
        if document_processor is None:
            from app.services.document_processor import get_document_processor

            document_processor = get_document_processor()
    except Exception as exc:
        logger.warning("BM25 finalize: cannot get DocumentProcessor case=%s: %s", cid, exc)
        return False

    if not document_processor.bm25_retriever.available:
        return False

    invalidate_bm25_index(cid, document_processor)
    with _case_lock(cid):
        t0 = time.monotonic()
        ok = bool(document_processor.prewarm_bm25_from_store(cid, force_rebuild=True))
        ms = int((time.monotonic() - t0) * 1000)
        if ok:
            logger.info("BM25 batch finalize ok case=%s ms=%s", cid, ms)
        else:
            logger.info("BM25 batch finalize skipped case=%s ms=%s", cid, ms)
        return ok


def invalidate_bm25_index(case_id: str, document_processor: Optional["DocumentProcessor"] = None) -> None:
    """Сброс индекса после переиндексации / удаления векторов."""
    cid = str(case_id or "").strip()
    if not cid:
        return
    try:
        from app.services.chat.case_file_catalog_cache import invalidate_case_catalog_cache

        invalidate_case_catalog_cache(cid)
    except Exception as exc:
        logger.debug("Catalog cache invalidate case=%s: %s", cid, exc)
    try:
        dp = document_processor
        if dp is None:
            from app.services.document_processor import get_document_processor

            dp = get_document_processor()
        dp.bm25_retriever.remove_index(cid)
    except Exception as exc:
        logger.debug("BM25 invalidate case=%s: %s", cid, exc)
