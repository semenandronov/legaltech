"""Tests for cached Docling DocumentConverter instances."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.document_converter_service import DocumentConverterService


@pytest.fixture(autouse=True)
def _clear_docling_cache():
    DocumentConverterService.reset_converter_cache_for_tests()
    yield
    DocumentConverterService.reset_converter_cache_for_tests()


def test_get_cached_converter_returns_same_instance_for_same_key():
    sentinel = MagicMock(name="pdf_no_ocr")
    with patch.object(
        DocumentConverterService,
        "_build_docling_pdf_converter",
        return_value=sentinel,
    ) as mock_build:
        first = DocumentConverterService.get_cached_converter(".pdf", do_ocr=False)
        second = DocumentConverterService.get_cached_converter(".pdf", do_ocr=False)

    assert first is sentinel
    assert second is sentinel
    mock_build.assert_called_once_with(do_ocr=False)


def test_get_cached_converter_different_keys_use_different_builds():
    no_ocr = MagicMock(name="no_ocr")
    with_ocr = MagicMock(name="with_ocr")
    with patch.object(
        DocumentConverterService,
        "_build_docling_pdf_converter",
        side_effect=[no_ocr, with_ocr],
    ) as mock_build:
        first = DocumentConverterService.get_cached_converter(".pdf", do_ocr=False)
        second = DocumentConverterService.get_cached_converter(".pdf", do_ocr=True)

    assert first is no_ocr
    assert second is with_ocr
    assert mock_build.call_count == 2


def test_converter_cache_key_normalizes_extension():
    assert DocumentConverterService._converter_cache_key("pdf", do_ocr=True) == (".pdf", True)
    assert DocumentConverterService._converter_cache_key(".PDF", do_ocr=False) == (".pdf", False)


def test_warmup_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr("app.services.document_converter_service.config.DOCLING_WARMUP_ON_STARTUP", False)
    with patch.object(DocumentConverterService, "get_cached_converter") as mock_get:
        ok = DocumentConverterService.warmup()
    assert ok is False
    mock_get.assert_not_called()


def test_warmup_uses_native_pdf_converter(monkeypatch):
    sentinel = MagicMock(name="warmup_converter")
    monkeypatch.setattr("app.services.document_converter_service.config.DOCLING_WARMUP_ON_STARTUP", True)
    with patch.object(
        DocumentConverterService,
        "get_cached_converter",
        return_value=sentinel,
    ) as mock_get, patch.object(
        DocumentConverterService,
        "_run_warmup_convert",
    ) as mock_convert:
        ok = DocumentConverterService.warmup()

    assert ok is True
    mock_get.assert_called_once_with(".pdf", do_ocr=False)
    mock_convert.assert_called_once_with(sentinel)
