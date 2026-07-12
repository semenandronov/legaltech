"""Tests for ingest progress contextvar."""
from __future__ import annotations

from app.services.ingest_progress import (
    IngestProgress,
    ingest_progress_scope,
    report_ingest_progress,
)


def test_report_without_sink_is_noop():
    report_ingest_progress(IngestProgress(stage="x", percent=1, message="m"))


def test_ingest_progress_scope_delivers_events():
    seen = []

    def sink(p: IngestProgress) -> None:
        seen.append(p.as_dict())

    with ingest_progress_scope(sink):
        report_ingest_progress(
            IngestProgress(stage="docling", percent=40, message="pages", pages_done=10, pages_total=100)
        )

    assert len(seen) == 1
    assert seen[0]["stage"] == "docling"
    assert seen[0]["percent"] == 40
    assert seen[0]["pages_done"] == 10
