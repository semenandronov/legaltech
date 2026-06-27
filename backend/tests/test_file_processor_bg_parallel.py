"""Parallel batch processing in file_processor_bg."""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest

from app.services import file_processor_bg as fpb
from app.services.file_processing_concurrency import reset_runtime_limits_for_tests


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_runtime_limits_for_tests()
    yield
    reset_runtime_limits_for_tests()


def test_process_files_background_uses_parallel_workers(monkeypatch):
    monkeypatch.setattr(
        "app.services.file_processing_concurrency.config.FILE_PROCESSING_MAX_PARALLEL_FILES",
        4,
        raising=False,
    )
    reset_runtime_limits_for_tests()

    active = 0
    max_active = 0
    guard = threading.Lock()
    per_file_delay = 0.12

    def _fake_process_one_file(db, file_id, case_id, document_processor):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        time.sleep(per_file_delay)
        with guard:
            active -= 1
        return []

    monkeypatch.setattr(fpb, "_process_one_file", _fake_process_one_file)
    monkeypatch.setattr(fpb, "_update_case_stats", lambda _db, _cid: None)
    monkeypatch.setattr(
        "app.services.document_processor.get_document_processor",
        lambda: MagicMock(prewarm_bm25_index=MagicMock()),
    )
    monkeypatch.setattr(fpb, "SessionLocal", lambda: MagicMock())

    started = time.monotonic()
    fpb.process_files_background(["f1", "f2", "f3"], "case-parallel")
    elapsed = time.monotonic() - started

    assert max_active >= 2
    # Sequential would be ~0.36s; parallel capped at ~0.12s + overhead.
    assert elapsed < per_file_delay * 2.5


def test_document_passport_uses_passport_slot(monkeypatch):
    calls: list[str] = []

    from contextlib import contextmanager

    @contextmanager
    def _tracking_slot():
        calls.append("slot")
        yield

    monkeypatch.setattr(fpb, "document_passport_slot", _tracking_slot)
    monkeypatch.setattr(
        "app.services.document_passport_graph.generate_document_passport",
        lambda **_kw: ("summary", ["point"], "договор", "v1"),
    )

    summary, points, doc_type, version = fpb._generate_llm_document_passport(
        text="текст",
        filename="doc.pdf",
        hint_doc_type="договор",
    )
    assert summary == "summary"
    assert points == ["point"]
    assert doc_type == "договор"
    assert version == "v1"
    assert calls == ["slot"]
