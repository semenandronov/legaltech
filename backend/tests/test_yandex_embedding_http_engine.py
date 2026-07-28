"""Unit tests for async Yandex embedding HTTP engine."""
from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import app.services.yandex_embedding_http as http_mod
from app.services.yandex_embedding_http import (
    YandexEmbeddingHttpEngine,
    _AdmissionControl,
    parse_openai_embeddings_json,
    reset_embedding_http_engine_for_tests,
)


def test_parse_openai_embeddings_json_accepts_standard_shape():
    payload = {
        "object": "list",
        "data": [{"object": "embedding", "embedding": [0.5] + [0.0] * 255, "index": 0}],
        "model": "emb://fld/text-search-doc/latest",
    }
    vec = parse_openai_embeddings_json(payload)
    assert len(vec) == 256
    assert vec[0] == 0.5


def test_embed_texts_delegates_to_engine_queue():
    reset_embedding_http_engine_for_tests()
    engine = YandexEmbeddingHttpEngine()

    with patch.object(engine, "embed_texts", return_value=[[0.1] * 256, [0.2] * 256]) as embed:
        with patch.object(http_mod, "_engine_singleton", engine):
            from app.services.yandex_embedding_http import get_embedding_http_engine

            out = get_embedding_http_engine().embed_texts(
                model="emb://fld/text-search-doc/latest",
                texts=["a", "b"],
            )
    assert len(out) == 2
    embed.assert_called_once()


def test_yandex_embeddings_uses_http_engine():
    from app.services.yandex_embeddings import YandexEmbeddings
    import app.services.yandex_embeddings as emb_mod

    inst = YandexEmbeddings.__new__(YandexEmbeddings)
    inst.sdk = MagicMock()
    inst.folder_id = "fld"
    inst._dns_ok = True

    texts = [f"chunk {i}" for i in range(5)]
    mock_engine = MagicMock()
    mock_engine.embed_texts.return_value = [[0.1] * 256 for _ in texts]

    with patch.object(emb_mod, "get_embedding_http_engine", return_value=mock_engine):
        with patch.object(emb_mod.config, "YANDEX_EMBEDDINGS_TRANSPORT", "openai"):
            with patch(
                "app.services.yandex_embeddings.split_text_for_embedding_api",
                side_effect=lambda t: [t],
            ):
                with patch.object(
                    emb_mod,
                    "_resolve_embedding_model_uri",
                    return_value="emb://fld/text-search-doc/latest",
                ):
                    out = inst.embed_documents(texts)

    assert len(out) == 5
    mock_engine.embed_texts.assert_called_once()
    assert mock_engine.embed_texts.call_args.kwargs.get("priority") is False


def test_priority_embed_processed_when_first_job():
    """embed_query uses priority=True; must not deadlock on empty regular queue."""
    reset_embedding_http_engine_for_tests()
    engine = YandexEmbeddingHttpEngine()
    model = "emb://fld/text-search-query/latest"
    vector = [0.3] + [0.0] * 255

    async def _fake_fetch(_client, _url, *, model, text, attempt=0, acquire_rps=None):
        if acquire_rps is not None:
            await acquire_rps()
        return vector

    with patch.object(engine, "_fetch_embedding", side_effect=_fake_fetch):
        engine._ensure_started()
        fut = engine._submit(model=model, text="query first", priority=True)
        result = fut.result(timeout=5.0)

    assert len(result) == 256
    assert result[0] == 0.3


def test_batch_cap_respects_max_parallel_burst(monkeypatch):
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_RPS_LIMIT", 100, raising=False)
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 8, raising=False)
    assert http_mod._batch_cap() == 8
    assert http_mod._max_in_flight() == 8
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 200, raising=False)
    assert http_mod._batch_cap() == 99
    assert http_mod._max_in_flight() == 100


def test_admission_token_bucket_refills(monkeypatch):
    async def _run():
        admission = _AdmissionControl(rps=10.0, max_in_flight=2)
        # Drain initial burst capacity.
        for _ in range(10):
            await admission.acquire_rps()
        t0 = time.monotonic()
        await admission.acquire_rps()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.05

    asyncio.run(_run())


def test_slow_request_does_not_block_siblings(monkeypatch):
    """
    Continuous pipeline regression: a slow in-flight request must not stall
    siblings that can take a free concurrency slot.

    With max_in_flight=2 and jobs [slow, fast, slow, fast]:
    - old batch-gather: ~2 * slow (~0.8s)
    - pipeline: both slows overlap → ~1 * slow (~0.4s)
    """
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_RPS_LIMIT", 100, raising=False)
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 2, raising=False)

    reset_embedding_http_engine_for_tests()
    engine = YandexEmbeddingHttpEngine()
    model = "emb://fld/text-search-doc/latest"
    slow_delay = 0.35

    async def _fake_fetch(_client, _url, *, model, text, attempt=0, acquire_rps=None):
        if acquire_rps is not None:
            await acquire_rps()
        if text.startswith("slow"):
            await asyncio.sleep(slow_delay)
        return [float(len(text) % 7)] + [0.0] * 255

    texts = ["slow-0", "fast-1", "slow-2", "fast-3"]

    with patch.object(engine, "_fetch_embedding", side_effect=_fake_fetch):
        t0 = time.monotonic()
        out = engine.embed_texts(model=model, texts=texts)
        elapsed = time.monotonic() - t0

    assert len(out) == 4
    # Pipeline should finish close to one slow delay, not two serialised batches.
    assert elapsed < slow_delay * 1.75, f"pipeline still head-of-line blocked: {elapsed:.3f}s"
    assert elapsed >= slow_delay * 0.8


def test_max_in_flight_is_respected(monkeypatch):
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_RPS_LIMIT", 100, raising=False)
    monkeypatch.setattr(http_mod.config, "YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS", 3, raising=False)

    reset_embedding_http_engine_for_tests()
    engine = YandexEmbeddingHttpEngine()
    model = "emb://fld/text-search-doc/latest"

    current = 0
    peak = 0
    lock = asyncio.Lock()

    async def _fake_fetch(_client, _url, *, model, text, attempt=0, acquire_rps=None):
        nonlocal current, peak
        if acquire_rps is not None:
            await acquire_rps()
        async with lock:
            current += 1
            peak = max(peak, current)
        await asyncio.sleep(0.05)
        async with lock:
            current -= 1
        return [0.1] + [0.0] * 255

    with patch.object(engine, "_fetch_embedding", side_effect=_fake_fetch):
        engine.embed_texts(model=model, texts=[f"t{i}" for i in range(12)])

    assert peak <= 3
    assert peak >= 2
