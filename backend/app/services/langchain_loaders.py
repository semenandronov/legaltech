"""LangChain document loaders for Legal AI Vault"""
from typing import List, Dict, Any, Optional, Mapping, Sequence
from langchain_community.document_loaders import (
    PyPDFLoader,
    UnstructuredWordDocumentLoader,
    TextLoader,
    CSVLoader,
)
from langchain_core.documents import Document
from app.config import config
import logging
import io
import tempfile
import os
import re

logger = logging.getLogger(__name__)


class DocumentLoaderService:
    """Service for loading documents using LangChain loaders"""

    @staticmethod
    def _pdf_min_chars_per_page() -> int:
        return max(
            1, int(getattr(config, "PDF_OCR_MIN_EXPECTED_CHARS_PER_PAGE", 5) or 5)
        )

    @staticmethod
    def _pdf_text_quality_ok(documents: List[Document]) -> bool:
        """
        Базовая эвристика качества OCR для PDF:
        считаем результат приемлемым, если есть осмысленный суммарный объем текста.
        """
        if not documents:
            return False
        pages_with_text = sum(1 for d in documents if (d.page_content or "").strip())
        total_chars = sum(len((d.page_content or "").strip()) for d in documents)
        min_chars_per_page = DocumentLoaderService._pdf_min_chars_per_page()
        min_total_chars = min_chars_per_page * max(1, pages_with_text)
        return total_chars >= min_total_chars

    @staticmethod
    def _inspect_pdf_page_signals(content: bytes) -> List[Dict[str, Any]]:
        """
        Per-page signals from PyMuPDF: native text length + visual content.
        Used to detect mixed PDFs (digital text on some pages, scans on others).
        """
        try:
            import fitz  # pymupdf
        except ImportError:
            logger.warning("pymupdf unavailable — cannot inspect PDF page coverage")
            return []

        signals: List[Dict[str, Any]] = []
        try:
            pdf_doc = fitz.open(stream=content, filetype="pdf")
            try:
                for page_num in range(len(pdf_doc)):
                    page = pdf_doc[page_num]
                    text = (page.get_text("text") or "").strip()
                    images = page.get_images(full=True) or []
                    drawings = page.get_drawings() or []
                    signals.append(
                        {
                            "page_index": page_num,
                            "text_chars": len(text),
                            "text": text,
                            "image_count": len(images),
                            "drawing_count": len(drawings),
                            "has_visual": bool(images) or bool(drawings),
                        }
                    )
            finally:
                pdf_doc.close()
        except Exception as exc:
            logger.warning("PDF page inspection failed: %s", exc, exc_info=True)
            return []
        return signals

    @staticmethod
    def _pages_needing_ocr(
        documents: Sequence[Document],
        page_signals: Sequence[Mapping[str, Any]],
        *,
        min_chars: Optional[int] = None,
    ) -> List[int]:
        """
        Pages that look like scans: little/no extractable text but have images/drawings.

        Blank pages (no text, no visuals) are left alone — they are not OCR targets.
        Pages with enough native (or PyMuPDF) text are kept as native.
        """
        threshold = (
            DocumentLoaderService._pdf_min_chars_per_page()
            if min_chars is None
            else max(1, int(min_chars))
        )
        weak: List[int] = []
        for idx, doc in enumerate(documents):
            pypdf_chars = len((doc.page_content or "").strip())
            sig = page_signals[idx] if idx < len(page_signals) else {}
            fitz_chars = int(sig.get("text_chars") or 0)
            effective = max(pypdf_chars, fitz_chars)
            if effective >= threshold:
                continue
            if bool(sig.get("has_visual")):
                weak.append(idx)
        return weak

    @staticmethod
    def _enrich_native_docs_from_fitz(
        documents: List[Document],
        page_signals: Sequence[Mapping[str, Any]],
        *,
        filename: str,
    ) -> None:
        """
        If PyPDF missed text that PyMuPDF can read, promote that text into the page doc.
        Avoids OCR when a better native extractor already has the content.
        """
        threshold = DocumentLoaderService._pdf_min_chars_per_page()
        for idx, doc in enumerate(documents):
            pypdf_chars = len((doc.page_content or "").strip())
            if pypdf_chars >= threshold:
                continue
            if idx >= len(page_signals):
                continue
            sig = page_signals[idx]
            fitz_text = str(sig.get("text") or "").strip()
            if len(fitz_text) < threshold:
                continue
            doc.page_content = fitz_text
            doc.metadata["extraction_source"] = "native_text_fitz"
            doc.metadata["ocr"] = False
            doc.metadata["source_file"] = filename
            doc.metadata["source_page"] = idx
            logger.info(
                "PDF %s page %s: promoted PyMuPDF text (%s chars, PyPDF had %s)",
                filename,
                idx + 1,
                len(fitz_text),
                pypdf_chars,
            )

    @staticmethod
    def _pdf_subset_bytes(content: bytes, page_indices: Sequence[int]) -> bytes:
        """Build a PDF containing only the given 0-based pages (stable order)."""
        import fitz  # pymupdf

        ordered = sorted({int(i) for i in page_indices})
        if not ordered:
            raise ValueError("page_indices must not be empty")
        src = fitz.open(stream=content, filetype="pdf")
        try:
            sub = fitz.open()
            try:
                for page_i in ordered:
                    if page_i < 0 or page_i >= len(src):
                        raise ValueError(
                            f"page index {page_i} out of range for PDF with {len(src)} pages"
                        )
                    sub.insert_pdf(src, from_page=page_i, to_page=page_i)
                return sub.tobytes()
            finally:
                sub.close()
        finally:
            src.close()

    @staticmethod
    def _normalize_page_docs(
        documents: List[Document],
        *,
        filename: str,
        default_extraction_source: str,
    ) -> List[Document]:
        """Ensure each page has stable source_page = enumerate index when missing."""
        out: List[Document] = []
        for idx, doc in enumerate(documents):
            md = dict(doc.metadata or {})
            md.setdefault("source_file", filename)
            md.setdefault("extraction_source", default_extraction_source)
            if "page" in md and md["page"] is not None:
                try:
                    md["source_page"] = int(md["page"])
                except (TypeError, ValueError):
                    md["source_page"] = idx
            else:
                md["source_page"] = idx
            out.append(Document(page_content=doc.page_content or "", metadata=md))
        return out

    @staticmethod
    def _merge_native_with_page_ocr(
        native_docs: List[Document],
        ocr_by_page: Mapping[int, Document],
        *,
        filename: str,
    ) -> List[Document]:
        """Keep strong native pages; replace scan pages with OCR results."""
        merged: List[Document] = []
        for idx, native in enumerate(native_docs):
            ocr_doc = ocr_by_page.get(idx)
            ocr_text = (ocr_doc.page_content or "").strip() if ocr_doc is not None else ""
            if ocr_doc is not None and ocr_text:
                md = dict(ocr_doc.metadata or {})
                md["source_file"] = filename
                md["source_page"] = idx
                md["ocr"] = True
                md["extraction_source"] = md.get("extraction_source") or "ocr"
                md["pdf_extraction"] = "hybrid_native_ocr"
                merged.append(Document(page_content=ocr_doc.page_content or "", metadata=md))
                continue
            md = dict(native.metadata or {})
            md["source_file"] = filename
            md["source_page"] = idx
            md["ocr"] = False
            md.setdefault("extraction_source", "native_text")
            md["pdf_extraction"] = "hybrid_native_ocr"
            merged.append(Document(page_content=native.page_content or "", metadata=md))
        return merged

    @staticmethod
    def _ocr_pdf(
        content: bytes,
        filename: str,
        page_indices: Optional[Sequence[int]] = None,
    ) -> List[Document]:
        """
        OCR fallback for scanned PDFs using PyMuPDF + Tesseract.
        If page_indices is set, only those 0-based pages are OCR'd.
        """
        try:
            import fitz  # pymupdf
            import pytesseract
            from PIL import Image
        except ImportError as e:
            logger.warning(f"OCR dependencies not available: {e}")
            return []

        documents = []
        try:
            pdf_doc = fitz.open(stream=content, filetype="pdf")
            try:
                if page_indices is None:
                    targets = list(range(len(pdf_doc)))
                else:
                    targets = sorted({int(i) for i in page_indices})
                for page_num in targets:
                    if page_num < 0 or page_num >= len(pdf_doc):
                        continue
                    page = pdf_doc[page_num]
                    # Render page to image at 300 DPI for good OCR quality
                    mat = fitz.Matrix(300 / 72, 300 / 72)
                    pix = page.get_pixmap(matrix=mat)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                    # OCR with Russian + English
                    text = pytesseract.image_to_string(img, lang="rus+eng")
                    text = text.strip()

                    if text:
                        documents.append(
                            Document(
                                page_content=text,
                                metadata={
                                    "source_file": filename,
                                    "source_page": page_num,
                                    "ocr": True,
                                    "ocr_engine": "tesseract",
                                    "extraction_source": "ocr",
                                },
                            )
                        )
            finally:
                pdf_doc.close()

            if documents:
                total_chars = sum(len(d.page_content) for d in documents)
                logger.info(
                    "OCR extracted text from %s: %s pages, %s chars",
                    filename,
                    len(documents),
                    total_chars,
                )

        except Exception as e:
            logger.error(f"OCR failed for {filename}: {e}", exc_info=True)

        return documents

    @staticmethod
    def _yandex_ocr_selected_pages(
        content: bytes,
        filename: str,
        page_indices: Sequence[int],
    ) -> Dict[int, Document]:
        """
        OCR only the given pages via Yandex Vision (subset PDF), remap to original indices.
        """
        from app.services.yandex_vision_ocr import yandex_vision_ocr_pdf_documents_for_langchain

        ordered = sorted({int(i) for i in page_indices})
        if not ordered:
            return {}
        subset = DocumentLoaderService._pdf_subset_bytes(content, ordered)
        ocr_docs = yandex_vision_ocr_pdf_documents_for_langchain(
            subset, filename, use_structured=True
        )
        by_page: Dict[int, Document] = {}
        for local_idx, doc in enumerate(ocr_docs or []):
            md = dict(doc.metadata or {})
            raw_local = md.get("source_page", local_idx)
            try:
                local_page = int(raw_local)
            except (TypeError, ValueError):
                local_page = local_idx
            if local_page < 0 or local_page >= len(ordered):
                if local_idx >= len(ordered):
                    continue
                local_page = local_idx
            real_page = ordered[local_page]
            md["source_page"] = real_page
            md["source_file"] = filename
            md["ocr"] = True
            md["extraction_source"] = "ocr"
            by_page[real_page] = Document(page_content=doc.page_content or "", metadata=md)
        return by_page

    @staticmethod
    def _tesseract_ocr_selected_pages(
        content: bytes,
        filename: str,
        page_indices: Sequence[int],
    ) -> Dict[int, Document]:
        docs = DocumentLoaderService._ocr_pdf(content, filename, page_indices=page_indices)
        return {
            int((d.metadata or {}).get("source_page", i)): d
            for i, d in enumerate(docs)
            if (d.page_content or "").strip()
        }

    @staticmethod
    def _ocr_selected_pages_with_fallback(
        content: bytes,
        filename: str,
        page_indices: Sequence[int],
        *,
        yandex_err_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Document]:
        """Yandex (preferred) → Tesseract for the given page indices only."""
        state = yandex_err_state if yandex_err_state is not None else {}
        use_yandex = getattr(config, "PDF_OCR_PREFER_YANDEX", True)
        if use_yandex:
            try:
                from app.services.yandex_vision_ocr import vision_api_configured

                if vision_api_configured():
                    by_page = DocumentLoaderService._yandex_ocr_selected_pages(
                        content, filename, page_indices
                    )
                    recovered = sum(
                        1
                        for i in page_indices
                        if i in by_page and (by_page[i].page_content or "").strip()
                    )
                    if recovered > 0:
                        logger.info(
                            "PDF %s: Yandex OCR recovered %s/%s weak pages",
                            filename,
                            recovered,
                            len(list(page_indices)),
                        )
                        return by_page
                    logger.warning(
                        "PDF %s: Yandex OCR returned no text for weak pages %s",
                        filename,
                        list(page_indices),
                    )
                else:
                    logger.warning(
                        "PDF %s: Yandex OCR not configured; Tesseract for weak pages %s",
                        filename,
                        list(page_indices),
                    )
            except Exception as yv_err:
                from app.services.yandex_vision_ocr import (
                    YandexOcrOperationFailedError,
                    yandex_ocr_is_temporary,
                    yandex_ocr_quota_or_temporary_message,
                )

                state["yandex_rate_limited"] = yandex_ocr_is_temporary(yv_err)
                state["yandex_op_failed"] = isinstance(yv_err, YandexOcrOperationFailedError)
                state["yv_err"] = yv_err
                logger.warning(
                    "PDF %s: Yandex OCR failed for weak pages (%s); Tesseract fallback",
                    filename,
                    yv_err,
                )
                if state.get("yandex_rate_limited"):
                    logger.warning(
                        "PDF %s: %s",
                        filename,
                        yandex_ocr_quota_or_temporary_message(yv_err),
                    )

        return DocumentLoaderService._tesseract_ocr_selected_pages(
            content, filename, page_indices
        )

    @staticmethod
    def _try_hybrid_native_ocr(
        content: bytes,
        filename: str,
        native_docs: List[Document],
    ) -> Optional[List[Document]]:
        """
        Mixed PDF path: keep digital pages, OCR only scan-like pages.
        Returns merged docs, or None if hybrid is not applicable / disabled / failed.
        """
        if not bool(getattr(config, "PDF_MIXED_PAGE_OCR_ENABLED", True)):
            return None
        if not native_docs:
            return None

        page_signals = DocumentLoaderService._inspect_pdf_page_signals(content)
        DocumentLoaderService._enrich_native_docs_from_fitz(
            native_docs, page_signals, filename=filename
        )
        weak_pages = DocumentLoaderService._pages_needing_ocr(native_docs, page_signals)
        if not weak_pages:
            return None

        strong_pages = [
            i
            for i, d in enumerate(native_docs)
            if i not in weak_pages and (d.page_content or "").strip()
        ]
        # Pure scan (no recoverable native pages): let the full-document OCR path handle it.
        if not strong_pages:
            logger.info(
                "PDF %s: all non-blank pages need OCR (%s) — using full-document OCR path",
                filename,
                weak_pages,
            )
            return None

        logger.info(
            "PDF %s: mixed native/scan — OCR pages %s (keep native %s)",
            filename,
            [p + 1 for p in weak_pages],
            [p + 1 for p in strong_pages],
        )
        ocr_by_page = DocumentLoaderService._ocr_selected_pages_with_fallback(
            content, filename, weak_pages
        )
        recovered = [i for i in weak_pages if i in ocr_by_page and (ocr_by_page[i].page_content or "").strip()]
        if not recovered:
            logger.warning(
                "PDF %s: hybrid OCR recovered 0/%s weak pages — falling back to full OCR",
                filename,
                len(weak_pages),
            )
            return None

        merged = DocumentLoaderService._merge_native_with_page_ocr(
            native_docs, ocr_by_page, filename=filename
        )
        logger.info(
            "PDF %s: hybrid extraction done — native=%s ocr=%s total_chars=%s",
            filename,
            len(strong_pages),
            len(recovered),
            sum(len((d.page_content or "").strip()) for d in merged),
        )
        return merged

    @staticmethod
    def load_pdf(content: bytes, filename: str) -> List[Document]:
        """
        Load PDF.

        Important:
        - Prefer the native text layer first (fast, deterministic, no OCR costs).
        - Mixed PDFs (some digital pages + some scans): OCR only weak pages, keep native text.
        - Fully scanned PDFs: Yandex Vision, then Tesseract fallback.
        """
        try:
            # Fallback #1: native text layer via PyPDF
            yandex_rate_limited = False
            yandex_op_failed = False
            yv_err = None
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name
            try:
                loader = PyPDFLoader(tmp_path)
                documents = loader.load()
                for idx, doc in enumerate(documents):
                    doc.metadata["source_file"] = filename
                    doc.metadata["extraction_source"] = "native_text"
                    doc.metadata["ocr"] = False
                    # Prefer LangChain's 0-based page index when present.
                    if doc.metadata.get("page") is not None:
                        try:
                            doc.metadata["source_page"] = int(doc.metadata["page"])
                        except (TypeError, ValueError):
                            doc.metadata["source_page"] = idx
                    else:
                        doc.metadata["source_page"] = idx
                        source = doc.metadata.get("source", "")
                        if source and "page" in str(source).lower():
                            try:
                                page_match = re.search(
                                    r"page[=:]?\s*(\d+)", str(source), re.IGNORECASE
                                )
                                if page_match:
                                    # source strings are often 1-based; store 0-based.
                                    doc.metadata["source_page"] = max(
                                        0, int(page_match.group(1)) - 1
                                    )
                            except Exception as e:
                                logger.debug(
                                    "Could not extract page number from source '%s': %s",
                                    source,
                                    e,
                                )

                total_text = "".join((d.page_content or "").strip() for d in documents)
                if documents and total_text.strip():
                    hybrid = DocumentLoaderService._try_hybrid_native_ocr(
                        content, filename, documents
                    )
                    if hybrid is not None:
                        return hybrid

                    page_signals = DocumentLoaderService._inspect_pdf_page_signals(content)
                    DocumentLoaderService._enrich_native_docs_from_fitz(
                        documents, page_signals, filename=filename
                    )
                    weak_pages = DocumentLoaderService._pages_needing_ocr(
                        documents, page_signals
                    )
                    if (
                        not weak_pages
                        and DocumentLoaderService._pdf_text_quality_ok(documents)
                    ):
                        documents = DocumentLoaderService._normalize_page_docs(
                            documents,
                            filename=filename,
                            default_extraction_source="native_text",
                        )
                        for d in documents:
                            d.metadata["pdf_extraction"] = "native"
                        logger.info(
                            "PDF %s: native text layer (PyPDFLoader), %s pages — "
                            "chunker will use Docling AST without OCR",
                            filename,
                            len(documents),
                        )
                        return documents
                    if weak_pages:
                        logger.info(
                            "PDF %s: native layer incomplete (weak pages %s) — full OCR path",
                            filename,
                            [p + 1 for p in weak_pages],
                        )
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            # OCR path (scanned PDF): Yandex Vision OCR (new API: model=page + bbox).
            use_yandex = getattr(config, "PDF_OCR_PREFER_YANDEX", True)
            if use_yandex:
                try:
                    from app.services.yandex_vision_ocr import (
                        vision_api_configured,
                        yandex_vision_ocr_pdf_documents_for_langchain,
                    )
                    if vision_api_configured():
                        yandex_docs = yandex_vision_ocr_pdf_documents_for_langchain(
                            content, filename, use_structured=True
                        )
                        if yandex_docs and DocumentLoaderService._pdf_text_quality_ok(yandex_docs):
                            logger.info(
                                "PDF %s: Yandex Vision OCR успешно, %s страниц",
                                filename,
                                len(yandex_docs),
                            )
                            return yandex_docs
                        logger.warning(
                            "PDF %s: Yandex OCR вернул мало текста (%s docs), переключаемся на локальный OCR fallback.",
                            filename,
                            len(yandex_docs or []),
                        )
                    else:
                        logger.warning(
                            "PDF %s: Yandex OCR не сконфигурирован, используем локальный OCR fallback.",
                            filename,
                        )
                except Exception as err:
                    from app.services.yandex_vision_ocr import (
                        YandexOcrOperationFailedError,
                        yandex_ocr_is_temporary,
                        yandex_ocr_operation_failed_message,
                        yandex_ocr_quota_or_temporary_message,
                    )
                    yv_err = err
                    yandex_rate_limited = yandex_ocr_is_temporary(err)
                    yandex_op_failed = isinstance(err, YandexOcrOperationFailedError)
                    logger.warning(
                        "PDF %s: Yandex OCR не удался (%s), используем локальный OCR fallback.",
                        filename,
                        err,
                    )
                    if yandex_rate_limited:
                        logger.warning(
                            "PDF %s: %s",
                            filename,
                            yandex_ocr_quota_or_temporary_message(err),
                        )

            # Local OCR fallback (Tesseract). Сканы не гоняем через Docling в лоадере:
            # Yandex/Tesseract текст передаётся в LegalChunkerV2, который пропускает _docling_pre_segmentation.
            scan_engine = str(getattr(config, "PDF_SCAN_OCR_ENGINE", "tesseract") or "tesseract").strip().lower()
            if scan_engine in ("docling_easyocr", "docling", "easyocr"):
                logger.warning(
                    "PDF %s: PDF_SCAN_OCR_ENGINE=%s игнорируется в ingest; "
                    "для сканов — Yandex OCR, локальный fallback — Tesseract (без Docling в лоадере).",
                    filename,
                    scan_engine,
                )

            ocr_docs = DocumentLoaderService._ocr_pdf(content, filename)
            if ocr_docs:
                return ocr_docs
            if yandex_op_failed and yv_err is not None:
                from app.services.yandex_vision_ocr import yandex_ocr_operation_failed_message

                raise ValueError(
                    yandex_ocr_operation_failed_message(yv_err)
                    + " Локальный OCR fallback не дал результата."
                )
            if yandex_rate_limited and yv_err is not None:
                from app.services.yandex_vision_ocr import yandex_ocr_quota_or_temporary_message

                raise ValueError(
                    yandex_ocr_quota_or_temporary_message(yv_err)
                    + " Локальный OCR fallback не настроен (pytesseract/pymupdf)."
                )
            raise ValueError(
                "Не удалось извлечь текст из PDF: отсутствует текстовый слой и OCR не дал результата."
            )
        except Exception as e:
            logger.error(f"Error loading PDF {filename}: {e}", exc_info=True)
            raise

    @staticmethod
    def load_docx(content: bytes, filename: str) -> List[Document]:
        """
        Load DOCX document using UnstructuredWordDocumentLoader
        
        Args:
            content: DOCX file content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        # Проверяем, что файл похож на DOCX (ZIP архив с определённой структурой)
        if len(content) < 100:
            raise ValueError(f"Файл {filename} слишком маленький для DOCX формата")
        
        # DOCX - это ZIP архив, должен начинаться с PK (0x50, 0x4B)
        has_zip_signature = content[:2] == b'PK'
        if not has_zip_signature:
            logger.warning(
                f"File {filename} does not have DOCX signature (PK header), "
                "will still attempt alternative DOCX parsers"
            )
        
        try:
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name
            
            try:
                documents = None
                unstructured_error = None
                docx_error = None
                mammoth_error = None
                
                # Try python-docx first (more reliable for basic DOCX)
                try:
                    from docx import Document as DocxDocument
                    doc = DocxDocument(io.BytesIO(content))
                    
                    # Извлекаем текст из параграфов
                    paragraphs_text = [para.text for para in doc.paragraphs if para.text.strip()]
                    
                    # Также извлекаем текст из таблиц
                    tables_text = []
                    for table in doc.tables:
                        for row in table.rows:
                            row_text = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip()])
                            if row_text:
                                tables_text.append(row_text)
                    
                    all_text = "\n".join(paragraphs_text)
                    if tables_text:
                        all_text += "\n\n[Таблицы]\n" + "\n".join(tables_text)
                    
                    if all_text.strip():
                        documents = [Document(page_content=all_text, metadata={"source_file": filename})]
                        logger.info(f"Loaded DOCX {filename} using python-docx: {len(all_text)} chars")
                except Exception as e:
                    docx_error = e
                    logger.debug(f"python-docx failed for {filename}: {e}")
                
                # If python-docx failed or returned empty, try UnstructuredWordDocumentLoader
                if not documents or not documents[0].page_content.strip():
                    try:
                        loader = UnstructuredWordDocumentLoader(tmp_path, mode="elements")
                        documents = loader.load()
                        logger.info(f"Loaded DOCX {filename} using UnstructuredWordDocumentLoader: {len(documents)} elements")
                    except Exception as e:
                        unstructured_error = e
                        logger.debug(f"UnstructuredWordDocumentLoader failed for {filename}: {e}")
                
                # Fallback: try mammoth (same as template converter) for better tolerance
                if not documents or not any(doc.page_content.strip() for doc in documents):
                    try:
                        import mammoth
                        result = mammoth.convert_to_html(io.BytesIO(content))
                        html = result.value or ""
                        # Basic HTML -> text conversion
                        text = html
                        text = text.replace("<br/>", "\n").replace("<br>", "\n")
                        text = text.replace("</p>", "\n").replace("</div>", "\n")
                        text = re.sub(r"<[^>]+>", " ", text)
                        text = re.sub(r"\s+\n", "\n", text)
                        text = re.sub(r"[ \t]+", " ", text).strip()
                        if text:
                            documents = [Document(page_content=text, metadata={"source_file": filename})]
                            logger.info(f"Loaded DOCX {filename} using mammoth: {len(text)} chars")
                    except Exception as e:
                        mammoth_error = e
                        logger.debug(f"mammoth failed for {filename}: {e}")
                
                # If all methods failed
                if not documents or not any(doc.page_content.strip() for doc in documents):
                    # Last resort: try plain text for files without DOCX signature
                    if not has_zip_signature:
                        try:
                            text_content = content.decode('utf-8', errors='ignore')
                            if text_content.strip():
                                logger.info(f"Loaded {filename} as plain text (not a valid DOCX)")
                                return [Document(page_content=text_content, metadata={"source_file": filename, "note": "loaded as text"})]
                        except Exception:
                            pass
                    
                    error_msgs = []
                    if docx_error:
                        error_msgs.append(f"python-docx: {str(docx_error)[:100]}")
                    if unstructured_error:
                        error_msgs.append(f"unstructured: {str(unstructured_error)[:100]}")
                    if mammoth_error:
                        error_msgs.append(f"mammoth: {str(mammoth_error)[:100]}")
                    
                        raise ValueError(
                        f"Не удалось извлечь текст из файла {filename}. "
                        f"Возможно, файл поврежден или имеет нестандартный формат. "
                        f"Ошибки: {'; '.join(error_msgs) if error_msgs else 'неизвестная ошибка'}"
                        )
                
                # Add filename to metadata
                for doc in documents:
                    if "source_file" not in doc.metadata:
                        doc.metadata["source_file"] = filename
                
                return documents
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error loading DOCX {filename}: {e}", exc_info=True)
            raise ValueError(
                f"Ошибка при загрузке файла {filename}: {str(e)[:200]}. "
                f"Убедитесь, что файл является корректным DOCX файлом."
            )
    
    @staticmethod
    def load_html(content: bytes, filename: str) -> List[Document]:
        """Load HTML (в т.ч. экспорт КонсультантПлюс) — текст для fallback, структура через Docling."""
        try:
            from app.services.consultant_html_preprocess import html_to_plain_text

            text = html_to_plain_text(content.decode("utf-8", errors="replace"))
            if not text.strip():
                raise ValueError("Пустой HTML после очистки")
            return [
                Document(
                    page_content=text,
                    metadata={
                        "source_file": filename,
                        "extraction_source": "html",
                    },
                )
            ]
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error loading HTML %s: %s", filename, e, exc_info=True)
            raise ValueError(f"Ошибка при загрузке HTML {filename}: {str(e)[:200]}")

    @staticmethod
    def load_txt(content: bytes, filename: str) -> List[Document]:
        """
        Load text document using TextLoader
        
        Args:
            content: Text file content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        try:
            # Decode content
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                text_content = content.decode('latin-1')
            
            # Save to temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as tmp_file:
                tmp_file.write(text_content)
                tmp_path = tmp_file.name
            
            try:
                loader = TextLoader(tmp_path, encoding='utf-8')
                documents = loader.load()
                
                # Add filename to metadata
                for doc in documents:
                    doc.metadata["source_file"] = filename
                
                logger.info(f"Loaded TXT {filename}: {len(documents)} documents")
                return documents
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Error loading TXT {filename}: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _xlsx_sheet_stream_to_document(sheet, sheet_name: str, filename: str) -> Optional[Document]:
        """
        Один лист → Document. Потоковый проход по строкам (без list(iter_rows) на весь лист).
        Forward-fill по столбцам для типичных объединённых ячеек.
        """
        text_lines: List[str] = [f"=== Лист: {sheet_name} ==="]
        header_row: Optional[List[str]] = None
        last_values: List[Any] = []

        for row in sheet.iter_rows(values_only=True):
            if header_row is None:
                if not row or not any(c is not None and str(c).strip() for c in row):
                    continue
                header_row = []
                for j, cell in enumerate(row):
                    if cell is not None and str(cell).strip():
                        header_row.append(str(cell).strip())
                    else:
                        header_row.append(f"Колонка{j + 1}")
                last_values = [None] * len(header_row)
                continue

            row_list = list(row) if row else []
            while len(row_list) > len(header_row):
                header_row.append(f"Колонка{len(header_row) + 1}")
                last_values.append(None)
            while len(row_list) < len(header_row):
                row_list.append(None)

            for j in range(len(header_row)):
                if row_list[j] is None:
                    row_list[j] = last_values[j]
                else:
                    last_values[j] = row_list[j]

            parts = []
            for j in range(len(header_row)):
                cell = row_list[j]
                val = str(cell).strip() if cell is not None else ""
                if not val or val.lower() in ("none", "nan", "-"):
                    continue
                parts.append(f"{header_row[j]}: {val}")
            if parts:
                text_lines.append(", ".join(parts))

        if header_row is None or len(text_lines) <= 1:
            return None
        sheet_text = "\n".join(text_lines)
        if not sheet_text.strip():
            return None
        return Document(
            page_content=sheet_text,
            metadata={"source_file": filename, "sheet_name": sheet_name, "source_type": "excel"},
        )

    @staticmethod
    def load_xlsx(content: bytes, filename: str) -> List[Document]:
        """
        Конвертирует XLSX в текст по листам.

        По умолчанию (если включено в конфиге и настроен Yandex Vision): **XLSX → PDF → Yandex OCR**
        по чанкам PDF (лимит страниц на запрос). Иначе — потоковое чтение openpyxl (read_only).
        Старый .xls здесь не поддерживается openpyxl — только текстовый fallback ниже не сработает для .xls.
        """
        try:
            if (
                filename.lower().endswith(".xlsx")
                and getattr(config, "XLSX_OCR_VIA_PDF_YANDEX", True)
            ):
                try:
                    from app.services.yandex_vision_ocr import (
                        vision_api_configured,
                        yandex_vision_ocr_pdf_documents_for_langchain,
                    )
                    from app.services.xlsx_pdf_for_vision import xlsx_bytes_to_pdf_bytes
                    import io as _io
                    from openpyxl import load_workbook as _load_workbook

                    # Skip PDF→OCR path for large files — ReportLab LongTable is very slow on 1000+ rows
                    _xlsx_ocr_max_rows = int(getattr(config, "XLSX_OCR_MAX_ROWS", 1000) or 1000)
                    _wb_check = _load_workbook(_io.BytesIO(content), read_only=True, data_only=True)
                    try:
                        _total_rows = sum(
                            _ws.max_row or 0 for _ws in _wb_check.worksheets
                        )
                    finally:
                        _wb_check.close()
                    _use_ocr = _total_rows <= _xlsx_ocr_max_rows
                    if not _use_ocr:
                        logger.info(
                            "XLSX %s: %d строк > лимит %d, пропускаем PDF→OCR, используем openpyxl",
                            filename, _total_rows, _xlsx_ocr_max_rows,
                        )

                    if vision_api_configured() and _use_ocr:
                        pdf_bytes = xlsx_bytes_to_pdf_bytes(content)
                        # Use 'table' model from new OCR API — much better for Excel-derived PDFs
                        docs = yandex_vision_ocr_pdf_documents_for_langchain(
                            pdf_bytes, filename, model="table"
                        )
                        for d in docs:
                            d.metadata["source_type"] = "excel"
                            d.metadata["xlsx_via_pdf_yandex"] = True
                        if docs:
                            logger.info(
                                "XLSX %s: PDF→Yandex Vision, фрагментов (стр./блоков) с текстом: %s",
                                filename,
                                len(docs),
                            )
                            return docs
                except Exception as ex:
                    logger.warning(
                        "XLSX→PDF→Yandex Vision не удалось (%s), используем текстовое извлечение openpyxl",
                        ex,
                    )

            from openpyxl import load_workbook

            documents: List[Document] = []

            try:
                wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
                try:
                    for sheet_name in wb.sheetnames:
                        sheet = wb[sheet_name]
                        doc = DocumentLoaderService._xlsx_sheet_stream_to_document(
                            sheet, sheet_name, filename
                        )
                        if doc:
                            documents.append(doc)
                finally:
                    wb.close()
                logger.info(
                    "Loaded XLSX %s (read_only): %s sheets with text",
                    filename,
                    len(documents),
                )
                return documents
            except Exception as e_ro:
                logger.warning(
                    "XLSX read_only недоступен (%s), открываю в обычном режиме",
                    e_ro,
                )
                documents = []
                wb2 = load_workbook(io.BytesIO(content), data_only=True)
                try:
                    for sheet_name in wb2.sheetnames:
                        sheet = wb2[sheet_name]
                        doc = DocumentLoaderService._xlsx_sheet_stream_to_document(
                            sheet, sheet_name, filename
                        )
                        if doc:
                            documents.append(doc)
                finally:
                    wb2.close()
                logger.info(
                    "Loaded XLSX %s (standard): %s sheets with text",
                    filename,
                    len(documents),
                )
                return documents
        except Exception as e:
            logger.error(f"Error loading XLSX {filename}: {e}", exc_info=True)
            raise

    @staticmethod
    def load_image_yandex_vision(content: bytes, filename: str) -> List[Document]:
        """
        Фото / скриншоты / сканы как отдельные файлы изображений — текст через Yandex Vision OCR.
        """
        from app.services.yandex_vision_ocr import yandex_vision_recognize_text

        text = yandex_vision_recognize_text(content, filename=filename)
        if not text.strip():
            text = "[На изображении не обнаружен распознаваемый текст.]"
        return [
            Document(
                page_content=text,
                metadata={
                    "source_file": filename,
                    "ocr": True,
                    "ocr_engine": "yandex_vision",
                },
            )
        ]
    
    @staticmethod
    def load_document(content: bytes, filename: str) -> List[Document]:
        """
        Load document based on file extension
        
        Args:
            content: File content as bytes
            filename: Original filename
            
        Returns:
            List of Document objects with metadata
        """
        # Get file extension
        _, ext = os.path.splitext(filename)
        ext = ext.lower()
        
        if ext == '.pdf':
            return DocumentLoaderService.load_pdf(content, filename)
        elif ext in ['.docx', '.doc']:
            return DocumentLoaderService.load_docx(content, filename)
        elif ext in ['.html', '.htm']:
            return DocumentLoaderService.load_html(content, filename)
        elif ext == '.txt':
            return DocumentLoaderService.load_txt(content, filename)
        elif ext in ('.html', '.htm'):
            return DocumentLoaderService.load_html(content, filename)
        elif ext in ['.xlsx', '.xls']:
            return DocumentLoaderService.load_xlsx(content, filename)
        elif ext == '.csv':
            from app.utils.file_parser import parse_csv
            text = parse_csv(content, filename)
            return [Document(page_content=text, metadata={"source_file": filename, "source_type": "csv"})]
        elif ext in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.gif'):
            return DocumentLoaderService.load_image_yandex_vision(content, filename)
        else:
            raise ValueError(f"Unsupported file format: {ext}")

