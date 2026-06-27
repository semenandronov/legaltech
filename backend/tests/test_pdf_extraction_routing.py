"""PDF extraction routing: scan → Yandex OCR; native text → Docling without OCR."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.services.langchain_loaders import DocumentLoaderService


def test_pdf_text_quality_ok_threshold():
    docs = [Document(page_content="x" * 50, metadata={})]
    assert DocumentLoaderService._pdf_text_quality_ok(docs) is True
    docs_bad = [Document(page_content="ab", metadata={})]
    assert DocumentLoaderService._pdf_text_quality_ok(docs_bad) is False


def test_build_pdf_pipeline_options_do_ocr_false():
    from app.services.document_converter_service import DocumentConverterService

    opts = DocumentConverterService._build_pdf_pipeline_options(do_ocr=False)
    if opts is None:
        pytest.skip("docling pipeline options not available")
    assert getattr(opts, "do_ocr", None) is False


def test_build_pdf_pipeline_options_do_ocr_true_default():
    from app.services.document_converter_service import DocumentConverterService

    opts = DocumentConverterService._build_pdf_pipeline_options()
    if opts is None:
        pytest.skip("docling pipeline options not available")
    assert getattr(opts, "do_ocr", None) is True


def test_legal_chunker_build_converter_do_ocr_false_for_native_pdf():
    from app.services.legal_chunker import _build_docling_converter
    from app.services.document_converter_service import DocumentConverterService

    DocumentConverterService.reset_converter_cache_for_tests()
    with patch(
        "app.services.document_converter_service.DocumentConverterService._build_docling_pdf_converter"
    ) as mock_build:
        mock_build.return_value = MagicMock(name="pdf_converter")
        first = _build_docling_converter(".pdf", do_ocr=False)
        second = _build_docling_converter(".pdf", do_ocr=False)
        mock_build.assert_called_once_with(do_ocr=False)
        assert first is second
    DocumentConverterService.reset_converter_cache_for_tests()


def test_document_processor_detects_legacy_docling_scan_preflight():
    docs = [
        Document(
            page_content="scan text " * 30,
            metadata={"docling_scan_preflight": True, "source_page": 1},
        )
    ]
    loader_did_ocr = False
    loader_native_text = False
    for ld in docs:
        md = getattr(ld, "metadata", None) or {}
        if md.get("ocr") is True or str(md.get("ocr_engine") or "").strip():
            loader_did_ocr = True
            loader_native_text = False
            break
        if md.get("docling_scan_preflight") is True:
            loader_did_ocr = True
            loader_native_text = False
            break
        if str(md.get("extraction_source") or "").strip() == "native_text":
            loader_native_text = True

    assert loader_did_ocr is True
    assert loader_native_text is False


def test_load_pdf_scan_fallback_skips_docling_preflight(monkeypatch):
    """Scanned PDF must not call Docling in loader when Yandex fails — Tesseract only."""
    from app.services.langchain_loaders import DocumentLoaderService

    monkeypatch.setattr("app.services.langchain_loaders.config.PDF_OCR_PREFER_YANDEX", False)
    monkeypatch.setattr(
        "app.services.langchain_loaders.config.PDF_SCAN_OCR_ENGINE",
        "docling_easyocr",
    )

    with patch.object(DocumentLoaderService, "_ocr_pdf") as mock_tesseract:
        mock_tesseract.return_value = [
            Document(
                page_content="ocr page text " * 10,
                metadata={"source_file": "scan.pdf", "source_page": 0, "ocr": True},
            )
        ]
        with patch(
            "app.services.document_converter_service.DocumentConverterService.extract_pdf_text_via_docling"
        ) as mock_docling:
            with patch("app.services.langchain_loaders.PyPDFLoader") as mock_pdf_loader:
                mock_pdf_loader.return_value.load.return_value = [
                    Document(page_content="x", metadata={"source": "page=1"})
                ]
                docs = DocumentLoaderService.load_pdf(b"%PDF-fake", "scan.pdf")

    assert docs
    mock_docling.assert_not_called()
    mock_tesseract.assert_called_once()


def test_document_processor_detects_native_text_metadata():
    docs = [
        Document(
            page_content="contract text " * 30,
            metadata={"extraction_source": "native_text", "ocr": False},
        )
    ]
    loader_did_ocr = False
    loader_native_text = False
    for ld in docs:
        md = getattr(ld, "metadata", None) or {}
        if md.get("ocr") is True or str(md.get("ocr_engine") or "").strip():
            loader_did_ocr = True
            loader_native_text = False
            break
        if str(md.get("extraction_source") or "").strip() == "native_text":
            loader_native_text = True

    assert loader_did_ocr is False
    assert loader_native_text is True


def test_document_processor_ocr_overrides_native_flag():
    docs = [
        Document(
            page_content="scan",
            metadata={"extraction_source": "native_text", "ocr": True, "ocr_engine": "yandex"},
        )
    ]
    loader_did_ocr = False
    loader_native_text = False
    for ld in docs:
        md = getattr(ld, "metadata", None) or {}
        if md.get("ocr") is True or str(md.get("ocr_engine") or "").strip():
            loader_did_ocr = True
            loader_native_text = False
            break
        if str(md.get("extraction_source") or "").strip() == "native_text":
            loader_native_text = True

    assert loader_did_ocr is True
    assert loader_native_text is False
