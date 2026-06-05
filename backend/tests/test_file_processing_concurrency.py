"""Concurrency limits for file ingestion."""
from app.services.file_processing_concurrency import (
    max_parallel_embeddings,
    max_parallel_files,
    max_parallel_passport,
    reset_runtime_limits_for_tests,
)


def test_max_parallel_defaults():
    reset_runtime_limits_for_tests()
    assert max_parallel_files() == 4
    assert max_parallel_passport() == 3
    assert max_parallel_embeddings() == 2


def test_max_parallel_clamped(monkeypatch):
    reset_runtime_limits_for_tests()
    monkeypatch.setattr(
        "app.services.file_processing_concurrency.config.FILE_PROCESSING_MAX_PARALLEL_FILES",
        99,
    )
    assert max_parallel_files() == 16
