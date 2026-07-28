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


def test_pages_needing_ocr_detects_scan_pages_keeps_blank_and_strong():
    docs = [
        Document(page_content="x" * 80, metadata={}),  # strong native
        Document(page_content="", metadata={}),  # scan
        Document(page_content="", metadata={}),  # blank (no visuals)
        Document(page_content="y" * 80, metadata={}),  # strong
    ]
    signals = [
        {"text_chars": 80, "has_visual": True, "image_count": 1, "drawing_count": 0},
        {"text_chars": 0, "has_visual": True, "image_count": 2, "drawing_count": 0},
        {"text_chars": 0, "has_visual": False, "image_count": 0, "drawing_count": 0},
        {"text_chars": 80, "has_visual": False, "image_count": 0, "drawing_count": 0},
    ]
    weak = DocumentLoaderService._pages_needing_ocr(docs, signals, min_chars=20)
    assert weak == [1]


def test_pages_needing_ocr_promotes_fitz_text_over_empty_pypdf():
    docs = [Document(page_content="", metadata={})]
    signals = [
        {
            "text_chars": 120,
            "text": "x" * 120,
            "has_visual": True,
            "image_count": 1,
            "drawing_count": 0,
        }
    ]
    DocumentLoaderService._enrich_native_docs_from_fitz(
        docs, signals, filename="demo.pdf"
    )
    weak = DocumentLoaderService._pages_needing_ocr(docs, signals, min_chars=20)
    assert weak == []
    assert len(docs[0].page_content) == 120


def test_merge_native_with_page_ocr_replaces_only_weak_pages():
    native = [
        Document(
            page_content="native-0",
            metadata={"extraction_source": "native_text", "ocr": False},
        ),
        Document(page_content="", metadata={"extraction_source": "native_text", "ocr": False}),
        Document(
            page_content="native-2",
            metadata={"extraction_source": "native_text", "ocr": False},
        ),
    ]
    ocr_by_page = {
        1: Document(
            page_content="ocr-page-1 with clause 4.1",
            metadata={"ocr": True, "ocr_engine": "yandex", "yandex_markdown": "ocr-page-1"},
        )
    }
    merged = DocumentLoaderService._merge_native_with_page_ocr(
        native, ocr_by_page, filename="mixed.pdf"
    )
    assert len(merged) == 3
    assert merged[0].page_content == "native-0"
    assert merged[0].metadata.get("ocr") is False
    assert merged[1].page_content.startswith("ocr-page-1")
    assert merged[1].metadata.get("ocr") is True
    assert merged[1].metadata.get("source_page") == 1
    assert merged[2].page_content == "native-2"
    assert all(d.metadata.get("pdf_extraction") == "hybrid_native_ocr" for d in merged)


def test_load_pdf_mixed_uses_hybrid_ocr_not_silent_native(monkeypatch):
    """Mixed PDF must not return native-only when middle pages are scans."""
    monkeypatch.setattr("app.services.langchain_loaders.config.PDF_MIXED_PAGE_OCR_ENABLED", True)
    monkeypatch.setattr("app.services.langchain_loaders.config.PDF_OCR_PREFER_YANDEX", True)
    monkeypatch.setattr(
        "app.services.langchain_loaders.config.PDF_OCR_MIN_EXPECTED_CHARS_PER_PAGE", 20
    )

    native_docs = [
        Document(page_content="A" * 100, metadata={"page": 0}),
        Document(page_content="", metadata={"page": 1}),
        Document(page_content="", metadata={"page": 2}),
        Document(page_content="B" * 100, metadata={"page": 3}),
    ]
    signals = [
        {"page_index": 0, "text_chars": 100, "text": "A" * 100, "image_count": 1, "drawing_count": 0, "has_visual": True},
        {"page_index": 1, "text_chars": 0, "text": "", "image_count": 2, "drawing_count": 0, "has_visual": True},
        {"page_index": 2, "text_chars": 0, "text": "", "image_count": 2, "drawing_count": 0, "has_visual": True},
        {"page_index": 3, "text_chars": 100, "text": "B" * 100, "image_count": 0, "drawing_count": 0, "has_visual": False},
    ]

    with patch.object(DocumentLoaderService, "_inspect_pdf_page_signals", return_value=signals):
        with patch.object(
            DocumentLoaderService,
            "_ocr_selected_pages_with_fallback",
            return_value={
                1: Document(
                    page_content="OCR page 2 with пункт 4.1",
                    metadata={"ocr": True, "ocr_engine": "yandex"},
                ),
                2: Document(
                    page_content="OCR page 3 rights section",
                    metadata={"ocr": True, "ocr_engine": "yandex"},
                ),
            },
        ) as mock_ocr:
            with patch("app.services.langchain_loaders.PyPDFLoader") as mock_pdf_loader:
                mock_pdf_loader.return_value.load.return_value = native_docs
                docs = DocumentLoaderService.load_pdf(b"%PDF-fake-mixed", "mixed.pdf")

    assert len(docs) == 4
    assert "пункт 4.1" in docs[1].page_content
    assert docs[0].metadata.get("ocr") is False
    assert docs[1].metadata.get("ocr") is True
    assert docs[2].metadata.get("ocr") is True
    assert docs[3].page_content.startswith("B")
    mock_ocr.assert_called_once()
    called_pages = list(mock_ocr.call_args.args[2])
    assert called_pages == [1, 2]


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
