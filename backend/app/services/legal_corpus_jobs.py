from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class LegalCorpusJob:
    job_id: str
    created_at: float
    status: str = "queued"  # queued | running | completed | failed
    message: str = ""
    progress_percent: float = 0.0
    total_files: int = 0
    processed_files: int = 0
    indexed_chunks: int = 0
    errors: list[dict] = field(default_factory=list)
    results: list[dict] = field(default_factory=list)
    # SSE queue: plain strings in SSE "data: ...\n\n" format
    events: "asyncio.Queue[str]" = field(default_factory=asyncio.Queue)
    finished_at: Optional[float] = None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "message": self.message,
            "progress_percent": self.progress_percent,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "indexed_chunks": self.indexed_chunks,
            "errors": self.errors,
            "results": self.results,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class LegalCorpusJobStore:
    """
    In-memory job registry for SSE progress.
    Suitable for single-process deployments / dev.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, LegalCorpusJob] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, *, total_files: int) -> LegalCorpusJob:
        job_id = str(uuid.uuid4())
        job = LegalCorpusJob(job_id=job_id, created_at=time.time(), total_files=int(max(0, total_files)))
        async with self._lock:
            self._jobs[job_id] = job
        return job

    async def get_job(self, job_id: str) -> Optional[LegalCorpusJob]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def drop_job(self, job_id: str) -> None:
        async with self._lock:
            self._jobs.pop(job_id, None)

    @staticmethod
    def sse_data(payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def emit(self, job: LegalCorpusJob, payload: Dict[str, Any]) -> None:
        await job.events.put(self.sse_data(payload))


legal_corpus_job_store = LegalCorpusJobStore()

