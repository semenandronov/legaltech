"""
Ingest progress reporting via contextvar (no call-stack plumbing).

Stages are free-form strings; UI/API read File.processing_progress JSON.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterator, Optional

ProgressSink = Callable[["IngestProgress"], None]

_progress_sink: ContextVar[Optional[ProgressSink]] = ContextVar(
    "ingest_progress_sink", default=None
)


@dataclass(frozen=True)
class IngestProgress:
    stage: str
    percent: int
    message: str = ""
    pages_done: Optional[int] = None
    pages_total: Optional[int] = None
    batch_index: Optional[int] = None
    batch_count: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["percent"] = max(0, min(100, int(self.percent)))
        return payload


@contextmanager
def ingest_progress_scope(sink: Optional[ProgressSink]) -> Iterator[None]:
    token = _progress_sink.set(sink)
    try:
        yield
    finally:
        _progress_sink.reset(token)


def report_ingest_progress(progress: IngestProgress) -> None:
    sink = _progress_sink.get()
    if sink is None:
        return
    try:
        sink(progress)
    except Exception:
        # Progress must never break ingest.
        pass
