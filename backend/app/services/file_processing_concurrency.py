"""Bounded concurrency for case file ingestion (OCR → LLM passport → embed/index).

Aligns parallel work with Yandex Vision OCR (~10 async starts/s), embeddings (~10/s),
and LLM quotas while keeping one SQLAlchemy session per file thread.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Dict, Iterator

from app.config import config

logger = logging.getLogger(__name__)

_case_metadata_locks: Dict[str, threading.Lock] = {}
_case_metadata_guard = threading.Lock()

_file_slots: threading.Semaphore | None = None
_passport_slots: threading.Semaphore | None = None
_embedding_slots: threading.Semaphore | None = None
_semaphore_guard = threading.Lock()


def _clamp_parallel(value: int, *, default: int, cap: int) -> int:
    if value <= 0:
        return default
    return min(value, cap)


def max_parallel_files() -> int:
    raw = int(getattr(config, "FILE_PROCESSING_MAX_PARALLEL_FILES", 4) or 4)
    return _clamp_parallel(raw, default=4, cap=16)


def max_parallel_passport() -> int:
    raw = int(getattr(config, "FILE_PROCESSING_MAX_PARALLEL_PASSPORT", 3) or 3)
    return _clamp_parallel(raw, default=3, cap=10)


def max_parallel_embeddings() -> int:
    raw = int(getattr(config, "FILE_PROCESSING_MAX_PARALLEL_EMBEDDINGS", 2) or 2)
    return _clamp_parallel(raw, default=2, cap=8)


def _get_semaphore(attr: str, factory) -> threading.Semaphore:
    global _file_slots, _passport_slots, _embedding_slots
    with _semaphore_guard:
        current = globals().get(attr)
        if current is None:
            current = factory()
            globals()[attr] = current
        return current


def _file_semaphore() -> threading.Semaphore:
    return _get_semaphore("_file_slots", lambda: threading.Semaphore(max_parallel_files()))


def _passport_semaphore() -> threading.Semaphore:
    return _get_semaphore(
        "_passport_slots", lambda: threading.Semaphore(max_parallel_passport())
    )


def _embedding_semaphore() -> threading.Semaphore:
    return _get_semaphore(
        "_embedding_slots", lambda: threading.Semaphore(max_parallel_embeddings())
    )


@contextmanager
def file_processing_slot() -> Iterator[None]:
    """Optional guard when work is not already bounded by a fixed-size thread pool."""
    sem = _file_semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


@contextmanager
def document_passport_slot() -> Iterator[None]:
    """Limits concurrent LLM passport generations (Foundation Models quota)."""
    sem = _passport_semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


@contextmanager
def embedding_index_slot() -> Iterator[None]:
    """Limits concurrent embed_documents + PGVector bulk inserts."""
    sem = _embedding_semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


@contextmanager
def case_metadata_lock(case_id: str) -> Iterator[None]:
    """Serialize Case.case_metadata / entity_index merges for one case."""
    cid = str(case_id or "").strip()
    if not cid:
        yield
        return
    with _case_metadata_guard:
        lock = _case_metadata_locks.get(cid)
        if lock is None:
            lock = threading.Lock()
            _case_metadata_locks[cid] = lock
    with lock:
        yield


def reset_runtime_limits_for_tests() -> None:
    """Drop lazily-created semaphores (unit tests only)."""
    global _file_slots, _passport_slots, _embedding_slots
    with _semaphore_guard:
        _file_slots = None
        _passport_slots = None
        _embedding_slots = None
    with _case_metadata_guard:
        _case_metadata_locks.clear()
