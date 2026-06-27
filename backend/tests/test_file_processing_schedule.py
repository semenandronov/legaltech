"""schedule_case_files_processing routes through file_ingest_scheduler."""
from __future__ import annotations

import asyncio

import pytest

from app.services import file_ingest_scheduler as sched
from app.services.file_processing_enqueue import schedule_case_files_processing


@pytest.fixture(autouse=True)
def _reset_scheduler():
    sched.reset_scheduler_for_tests()
    yield
    sched.reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_schedule_case_files_processing_enqueues_via_scheduler(monkeypatch):
    captured: list[tuple[list[str], str]] = []

    async def _spy_enqueue(file_ids, case_id):
        captured.append((list(file_ids), case_id))
        await asyncio.sleep(0)

    monkeypatch.setattr(sched, "_run_batch", _spy_enqueue)
    monkeypatch.setattr(
        "app.services.file_ingest_scheduler.config.file_processing_via_worker",
        lambda: False,
    )

    schedule_case_files_processing("case-sched", ["f1", "f2"])
    await asyncio.sleep(0.05)

    assert len(captured) == 1
    assert set(captured[0][0]) == {"f1", "f2"}
    assert captured[0][1] == "case-sched"
