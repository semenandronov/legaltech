"""Ingest uses bounded parallel pool — no legacy global lock."""
from __future__ import annotations

from app.services import file_processor_bg as fpb


def test_background_processing_lock_removed():
    assert not hasattr(fpb, "_background_processing_lock")


def test_process_files_background_uses_thread_pool():
    import inspect

    source = inspect.getsource(fpb.process_files_background)
    assert "ThreadPoolExecutor" in source
    assert "max_parallel_files" in source
