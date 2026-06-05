"""Case-scoped file ingest scheduler: coalesce + limited cross-case parallelism."""
from __future__ import annotations

import asyncio

import pytest

from app.services import file_ingest_scheduler as sched


@pytest.fixture(autouse=True)
def _reset():
    sched.reset_scheduler_for_tests()
    yield
    sched.reset_scheduler_for_tests()


@pytest.mark.asyncio
async def test_enqueue_coalesces_same_case(monkeypatch):
    batches: list[list[str]] = []

    async def _fake_run(file_ids, case_id):
        await asyncio.to_thread(
            lambda: batches.append(list(file_ids)),
        )

    monkeypatch.setattr(sched, "_run_batch", _fake_run)
    monkeypatch.setattr(
        "app.services.file_ingest_scheduler.config.file_processing_via_worker",
        lambda: False,
    )

    await sched.enqueue_case_files(["f1", "f2"], "case-a")
    await sched.enqueue_case_files(["f3"], "case-a")

    st = await sched._get_state("case-a")
    if st.drain_task:
        await st.drain_task

    assert len(batches) == 1
    assert set(batches[0]) == {"f1", "f2", "f3"}


@pytest.mark.asyncio
async def test_two_cases_can_run_concurrently(monkeypatch):
    monkeypatch.setattr(
        "app.services.file_ingest_scheduler.config.FILE_PROCESSING_MAX_CONCURRENT_CASES",
        2,
        raising=False,
    )
    sched.reset_scheduler_for_tests()

    active = 0
    max_active = 0
    gate = asyncio.Event()

    async def _slow_batch(file_ids, case_id):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        gate.set()
        await asyncio.sleep(0.08)
        active -= 1

    monkeypatch.setattr(sched, "_run_batch", _slow_batch)
    monkeypatch.setattr(
        "app.services.file_ingest_scheduler.config.file_processing_via_worker",
        lambda: False,
    )

    t1 = asyncio.create_task(sched.enqueue_case_files(["a1"], "case-1"))
    t2 = asyncio.create_task(sched.enqueue_case_files(["b1"], "case-2"))
    await asyncio.gather(t1, t2)
    await asyncio.wait_for(gate.wait(), timeout=2.0)

    st1 = await sched._get_state("case-1")
    st2 = await sched._get_state("case-2")
    if st1.drain_task:
        await st1.drain_task
    if st2.drain_task:
        await st2.drain_task

    assert max_active >= 2
