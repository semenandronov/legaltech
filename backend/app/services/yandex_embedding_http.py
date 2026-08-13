"""Async OpenAI-compat Yandex embeddings with continuous pipeline admission.

Yandex accepts exactly one text per /embeddings request. This module runs a
process-wide background asyncio worker that:

- reuses one httpx.AsyncClient (keep-alive / TLS session reuse);
- admits work through a continuous pipeline (not batch-then-wait);
- caps starts with a token-bucket RPS limiter;
- caps concurrency with an in-flight semaphore so one slow request never
  blocks siblings that already have a free slot;
- retries transient errors including HTTP 429 with exponential backoff
  (each retry re-acquires an RPS token).

All sync callers (LangChain embed_documents, file ingest threads) share one
global queue so concurrent files do not oversubscribe the API quota.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional, Set

from app.config import config
from app.services.yandex_privacy import apply_data_logging_headers

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 256
_MAX_429_RETRIES = 6
_REQUEST_TIMEOUT_SEC = 60.0
_DEFAULT_MAX_IN_FLIGHT = 32


def embedding_vector_dim() -> int:
    return _EMBEDDING_DIM


def _embedding_rps_limit() -> int:
    raw = int(getattr(config, "YANDEX_EMBEDDING_RPS_LIMIT", 10) or 10)
    return max(1, min(raw, 500))


def _rps_budget() -> float:
    """Effective start rate. Leave one token of headroom against sliding-window 429s."""
    return float(max(1, _embedding_rps_limit() - 1))


def _max_in_flight() -> int:
    """Max concurrent HTTP embedding requests (independent of RPS window wait)."""
    raw = int(
        getattr(config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 0)
        or getattr(config, "YANDEX_EMBEDDING_BATCH_SIZE", 0)
        or _DEFAULT_MAX_IN_FLIGHT
    )
    return max(1, min(raw, _embedding_rps_limit()))


# Backward-compatible aliases used by older tests / callers.
def _max_parallel_burst() -> int:
    return _max_in_flight()


def _micro_batch_size() -> int:
    return max(1, _embedding_rps_limit() - 1)


def _batch_cap() -> int:
    return min(_micro_batch_size(), _max_in_flight())


def _window_seconds() -> float:
    return 1.0


def _yandex_openai_compat_http_headers() -> dict[str, str]:
    from app.services.yandex_openai_llm import resolve_yandex_folder_id

    api_key = (getattr(config, "YANDEX_API_KEY", "") or "").strip()
    iam_token = (getattr(config, "YANDEX_IAM_TOKEN", "") or "").strip()
    folder = resolve_yandex_folder_id()
    if not folder:
        raise ValueError("Yandex embeddings HTTP: YANDEX_FOLDER_ID is required.")
    if api_key:
        authorization = f"Api-Key {api_key}"
    elif iam_token:
        authorization = f"Bearer {iam_token}"
    else:
        raise ValueError("Yandex embeddings HTTP: set YANDEX_API_KEY or YANDEX_IAM_TOKEN.")
    return apply_data_logging_headers(
        {
            "Authorization": authorization,
            "x-folder-id": folder,
            "Content-Type": "application/json",
        }
    )


def _yandex_openai_compat_base_url() -> str:
    from app.services.yandex_openai_llm import _DEFAULT_BASE_URL

    return (getattr(config, "YANDEX_OPENAI_COMPAT_BASE_URL", None) or _DEFAULT_BASE_URL).strip()


def parse_openai_embeddings_json(payload: Any) -> List[float]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"OpenAI-compat embeddings: expected JSON object, got {type(payload)}")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise RuntimeError(
            f"OpenAI-compat embeddings: expected 1 vector in data, got "
            f"{len(data) if isinstance(data, list) else 'n/a'}"
        )
    item = data[0]
    if isinstance(item, dict):
        emb = item.get("embedding")
    else:
        emb = getattr(item, "embedding", None)
    if isinstance(emb, tuple):
        emb = list(emb)
    if not isinstance(emb, list) or len(emb) != _EMBEDDING_DIM:
        raise RuntimeError(
            f"OpenAI-compat embeddings: unexpected embedding size "
            f"{len(emb) if isinstance(emb, list) else 'n/a'}"
        )
    return [float(x) for x in emb]


def _is_transient_http_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "429",
            "rate",
            "resource_exhausted",
            "unavailable",
            "timeout",
            "timed out",
            "connection reset",
            "connection error",
        )
    )


@dataclass(frozen=True)
class _EmbedJob:
    model: str
    text: str
    future: Future[List[float]]


class _AdmissionControl:
    """Token-bucket RPS + in-flight semaphore.

    Runs on a single asyncio event loop — no locking required beyond the
    cooperative await points.
    """

    def __init__(self, *, rps: float, max_in_flight: int) -> None:
        self._rps = max(1.0, float(rps))
        self._tokens = self._rps
        self._updated = time.monotonic()
        self._sem = asyncio.Semaphore(max(1, int(max_in_flight)))
        self.max_in_flight = max(1, int(max_in_flight))

    async def acquire_inflight(self) -> None:
        await self._sem.acquire()

    def release_inflight(self) -> None:
        self._sem.release()

    async def acquire_rps(self) -> None:
        while True:
            now = time.monotonic()
            elapsed = now - self._updated
            if elapsed > 0:
                self._tokens = min(self._rps, self._tokens + elapsed * self._rps)
                self._updated = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._rps
            await asyncio.sleep(wait)


class YandexEmbeddingHttpEngine:
    """Process-wide async HTTP embedding worker (singleton)."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[_EmbedJob]] = None
        self._priority_queue: Optional[asyncio.Queue[_EmbedJob]] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()
        self._inflight_tasks: Set[asyncio.Task[None]] = set()

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            return self._loop
        with self._start_lock:
            if self._loop is not None and self._thread is not None and self._thread.is_alive():
                return self._loop
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._thread_main,
                name="yandex-embedding-http",
                daemon=True,
            )
            self._thread.start()
            if not self._ready.wait(timeout=30.0):
                raise RuntimeError("Yandex embedding HTTP engine failed to start within 30s")
            assert self._loop is not None
            return self._loop

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._queue = asyncio.Queue()
        self._priority_queue = asyncio.Queue()
        self._ready.set()
        try:
            loop.run_until_complete(self._run_forever())
        except Exception as exc:
            logger.error("Yandex embedding HTTP engine crashed: %s", exc, exc_info=True)
            raise

    async def _run_forever(self) -> None:
        import httpx

        assert self._queue is not None
        max_flight = _max_in_flight()
        rps = _rps_budget()
        admission = _AdmissionControl(rps=rps, max_in_flight=max_flight)
        limits = httpx.Limits(
            max_keepalive_connections=max(20, max_flight * 2),
            max_connections=max(50, max_flight * 4),
        )
        url = f"{_yandex_openai_compat_base_url().rstrip('/')}/embeddings"
        logger.info(
            "Yandex embedding HTTP pipeline started (rps=%.0f max_in_flight=%s)",
            rps,
            max_flight,
        )

        async with httpx.AsyncClient(limits=limits, timeout=_REQUEST_TIMEOUT_SEC) as client:
            while True:
                job = await self._dequeue_job()
                # Hold an in-flight slot before spawning so the dispatcher
                # back-pressures on concurrency, not on RPS alone.
                await admission.acquire_inflight()
                task = asyncio.create_task(
                    self._process_job(client, url, job, admission),
                    name="yandex-emb-job",
                )
                self._inflight_tasks.add(task)
                task.add_done_callback(self._inflight_tasks.discard)

    async def _process_job(
        self,
        client: Any,
        url: str,
        job: _EmbedJob,
        admission: _AdmissionControl,
    ) -> None:
        try:
            if job.future.cancelled():
                return
            try:
                vector = await self._fetch_embedding(
                    client,
                    url,
                    model=job.model,
                    text=job.text,
                    acquire_rps=admission.acquire_rps,
                )
                if not job.future.cancelled():
                    job.future.set_result(vector)
            except Exception as exc:
                if not job.future.cancelled():
                    job.future.set_exception(exc)
        finally:
            admission.release_inflight()

    def _queues_empty(self) -> bool:
        assert self._queue is not None and self._priority_queue is not None
        return self._queue.empty() and self._priority_queue.empty()

    async def _dequeue_job(self) -> _EmbedJob:
        """Return the next job, preferring the priority queue.

        Must not block only on the regular queue: chat/search embed_query uses
        priority=True and can be the first request after worker start.
        """
        assert self._queue is not None and self._priority_queue is not None
        while True:
            try:
                return self._priority_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

            pri_task = asyncio.create_task(self._priority_queue.get())
            reg_task = asyncio.create_task(self._queue.get())
            done, pending = await asyncio.wait(
                [pri_task, reg_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            return done.pop().result()

    def _dequeue_job_nowait(self) -> _EmbedJob:
        assert self._queue is not None and self._priority_queue is not None
        try:
            return self._priority_queue.get_nowait()
        except asyncio.QueueEmpty:
            return self._queue.get_nowait()

    async def _execute_job(self, client: Any, url: str, job: _EmbedJob) -> None:
        """Legacy helper kept for tests that patch ``_fetch_embedding``."""
        if job.future.cancelled():
            return
        try:
            vector = await self._fetch_embedding(client, url, model=job.model, text=job.text)
            if not job.future.cancelled():
                job.future.set_result(vector)
        except Exception as exc:
            if not job.future.cancelled():
                job.future.set_exception(exc)

    async def _fetch_embedding(
        self,
        client: Any,
        url: str,
        *,
        model: str,
        text: str,
        attempt: int = 0,
        acquire_rps: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> List[float]:
        if acquire_rps is not None:
            await acquire_rps()

        headers = _yandex_openai_compat_http_headers()
        body = {
            "model": model,
            "input": text,
            "encoding_format": "float",
        }
        response = await client.post(url, headers=headers, json=body)

        if response.status_code == 429:
            if attempt >= _MAX_429_RETRIES:
                raise RuntimeError(
                    f"Yandex embeddings HTTP 429 after {_MAX_429_RETRIES} retries"
                )
            delay = min(30.0, (2**attempt) * (0.8 + 0.4 * random.random()))
            logger.warning(
                "Yandex embeddings HTTP 429; retry in %.2fs (attempt %s)",
                delay,
                attempt + 1,
            )
            await asyncio.sleep(delay)
            return await self._fetch_embedding(
                client,
                url,
                model=model,
                text=text,
                attempt=attempt + 1,
                acquire_rps=acquire_rps,
            )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Yandex embeddings HTTP {response.status_code}: {response.text[:500]}"
            )

        try:
            return parse_openai_embeddings_json(response.json())
        except Exception as exc:
            if attempt >= 2 or not _is_transient_http_error(exc):
                raise
            await asyncio.sleep(0.35 * (2**attempt))
            return await self._fetch_embedding(
                client,
                url,
                model=model,
                text=text,
                attempt=attempt + 1,
                acquire_rps=acquire_rps,
            )

    def _submit(self, *, model: str, text: str, priority: bool = False) -> Future[List[float]]:
        loop = self._ensure_started()
        assert self._queue is not None and self._priority_queue is not None
        fut: Future[List[float]] = Future()
        job = _EmbedJob(model=model, text=text, future=fut)

        def _enqueue() -> None:
            assert self._queue is not None and self._priority_queue is not None
            if priority:
                self._priority_queue.put_nowait(job)
            else:
                self._queue.put_nowait(job)

        loop.call_soon_threadsafe(_enqueue)
        return fut

    def embed_texts(self, *, model: str, texts: List[str], priority: bool = False) -> List[List[float]]:
        """Blocking embed for one or many texts (global RPS queue)."""
        if not texts:
            return []
        futures = [self._submit(model=model, text=t, priority=priority) for t in texts]
        return [f.result(timeout=600.0) for f in futures]


_engine_singleton: Optional[YandexEmbeddingHttpEngine] = None
_engine_lock = threading.Lock()


def get_embedding_http_engine() -> YandexEmbeddingHttpEngine:
    global _engine_singleton
    if _engine_singleton is None:
        with _engine_lock:
            if _engine_singleton is None:
                _engine_singleton = YandexEmbeddingHttpEngine()
    return _engine_singleton


def reset_embedding_http_engine_for_tests() -> None:
    """Drop singleton (unit tests only; does not stop a running worker thread)."""
    global _engine_singleton
    with _engine_lock:
        _engine_singleton = None
