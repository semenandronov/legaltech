"""Tests for parallel Yandex OCR chunk scheduling."""
from __future__ import annotations

from unittest.mock import patch

from app.services import yandex_vision_ocr as ocr


def test_async_parallel_disabled_for_single_chunk():
    assert ocr._async_parallel_enabled(1) is False


def test_async_parallel_enabled_for_multi_chunk(monkeypatch):
    from app import config as cfg

    monkeypatch.setattr(cfg.config, "YANDEX_OCR_ASYNC_PARALLEL_ENABLED", True, raising=False)
    assert ocr._async_parallel_enabled(3) is True


def test_async_max_parallel_workers_capped(monkeypatch):
    from app import config as cfg

    monkeypatch.setattr(cfg.config, "YANDEX_OCR_ASYNC_MAX_PARALLEL_CHUNKS", 5, raising=False)
    assert ocr._async_max_parallel_workers(20) == 5
    assert ocr._async_max_parallel_workers(2) == 2


def test_ocr_http_start_timeout_pair():
    connect, read = ocr._ocr_http_timeout_pair(180.0)
    assert connect < read
    assert read == 180.0


def test_run_structured_parallel_invokes_start_and_poll():
    chunks = [
        ocr._PdfOcrChunkSpec(chunk_index=0, p0=0, p1=1, b64="YQ=="),
        ocr._PdfOcrChunkSpec(chunk_index=1, p0=1, p1=2, b64="Yg=="),
    ]
    started_ops = [
        ocr._StartedOcrOp(chunk=chunks[0], op_id="op0", model="page"),
        ocr._StartedOcrOp(chunk=chunks[1], op_id="op1", model="page"),
    ]

    class FakePage:
        def __init__(self, idx: int):
            self.page_index = idx
            self.page_text = f"text{idx}"

    with patch.object(ocr, "_start_chunk_ocr", side_effect=started_ops):
        with patch.object(ocr, "_shared_initial_poll_delay_sec", return_value=0.0):
            with patch.object(
                ocr,
                "_poll_structured_recognition",
                side_effect=[
                    [FakePage(0)],
                    [FakePage(1)],
                ],
            ):
                pages = ocr._run_pdf_chunks_structured_parallel(
                    chunks,
                    ocr_model="page",
                    timeout_sec=60,
                    language_codes=["*"],
                    filename="test.pdf",
                )
    assert len(pages) == 2
    assert pages[0].page_index == 0
    assert pages[1].page_index == 1
