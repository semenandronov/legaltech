"""
Ingest progress reporting via contextvar (no call-stack plumbing).

Stages are free-form strings; UI/API read File.processing_progress JSON.

``File.processing_progress`` is an accumulating JSON bag: stage updates and
durable ingest artifacts (e.g. ``document_outline_v1``) share one column.
Writers must merge-patch keys via ``apply_processing_progress`` — never replace
the whole dict mid-run, or artifacts written earlier in the same ingest are lost.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterator, Mapping, Optional

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


def apply_processing_progress(file_model: Any, updates: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Merge-patch ``File.processing_progress``.

    Reassigns a new dict so SQLAlchemy JSON change detection always fires.
    """
    current = getattr(file_model, "processing_progress", None)
    base: Dict[str, Any] = dict(current) if isinstance(current, dict) else {}
    base.update(dict(updates))
    file_model.processing_progress = base
    return base


def reset_processing_progress(file_model: Any, updates: Mapping[str, Any]) -> Dict[str, Any]:
    """Replace progress at the start of a new ingest (clears prior-run artifacts)."""
    payload = dict(updates)
    file_model.processing_progress = payload
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
