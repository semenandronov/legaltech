"""Tests for tabular extraction runtime (parallelism + in-flight guard)."""
import asyncio

import pytest

from app.services.tabular_extraction_runtime import (
    release_column_run,
    reset_tabular_extraction_runtime_for_tests,
    tabular_max_parallel_cells,
    try_acquire_column_run,
)


@pytest.fixture(autouse=True)
def _reset_runtime():
    reset_tabular_extraction_runtime_for_tests()
    yield
    reset_tabular_extraction_runtime_for_tests()


@pytest.mark.asyncio
async def test_try_acquire_column_run_rejects_duplicate():
    assert await try_acquire_column_run("rev-1", "col-1") is True
    assert await try_acquire_column_run("rev-1", "col-1") is False
    await release_column_run("rev-1", "col-1")
    assert await try_acquire_column_run("rev-1", "col-1") is True


def test_tabular_max_parallel_cells_default():
    assert tabular_max_parallel_cells() >= 1
