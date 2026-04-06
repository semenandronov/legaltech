"""LangChain document loaders for Legal AI Vault"""
from typing import List, Dict, Any, Optional
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
    def _pdf_text_quality_ok(documents: List[Document]) -> bool:
        """
        Базовая эвристика качества OCR для PDF:
        считаем результат приемлемым, если есть осмысленный суммарный объем текста.
        """
        if not documents:
            return False
        pages_with_text = sum(1 for d in documents if (d.page_content or "").strip())
        total_chars = sum(len((d.page_content or "").strip()) for d in documents)
        min_chars_per_page = max(
            1, int(getattr(config, "PDF_OCR_MIN_EXPECTED_CHARS_PER_PAGE", 5) or 5)
        )
        min_total_chars = min_chars_per_page * max(1, pages_with_text)
        return total_chars >= min_total_chars

    @staticmethod
    def _ocr_pdf(content: bytes, filename: str) -> List[Document]:
        """
        OCR fallback for scanned PDFs using PyMuPDF + Tesseract.
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
            for page_num in range(len(pdf_doc)):
                page = pdf_doc[page_num]
                # Render page to image at 300 DPI for good OCR quality
                mat = fitz.Matrix(300 / 72, 300 / 72)
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                # OCR with Russian + English
                text = pytesseract.image_to_string(img, lang='rus+eng')
                text = text.strip()

                if text:
                    documents.append(Document(
                        page_content=text,
                        metadata={
                            "source_file": filename,
                            "source_page": page_num,
                            "ocr": True,
                        }
                    ))
            pdf_doc.close()

            if documents:
                total_chars = sum(len(d.page_content) for d in documents)
                logger.info(f"OCR extracted text from {filename}: {len(documents)} pages, {total_chars} chars")

        except Exception as e:
            logger.error(f"OCR failed for {filename}: {e}", exc_info=True)

        return documents

    @staticmethod
    def load_pdf(content: bytes, filename: str) -> List[Document]:
        """
        Load PDF using Yandex Vision OCR first (for all PDFs), with safe fallbacks.
        """
        try:
            use_yandex = getattr(config, "PDF_OCR_PREFER_YANDEX", True)
            yandex_rate_limited = False
            if use_yandex:
                try:
                    from app.services.yandex_vision_ocr import (
                        vision_api_configured,
                        yandex_vision_ocr_pdf_documents_for_langchain,
                    )

                    if vision_api_configured():
                        yandex_docs = yandex_vision_ocr_pdf_documents_for_langchain(
                            content, filename
                        )
                        if yandex_docs and DocumentLoaderService._pdf_text_quality_ok(yandex_docs):
                            logger.info(
                                "PDF %s: Yandex Vision OCR успешно, %s страниц",
                                filename,
                                len(yandex_docs),
                            )
                            return yandex_docs
                        logger.warning(
                            "PDF %s: Yandex OCR вернул мало текста (%s docs), переключаемся на fallback.",
                            filename,
                            len(yandex_docs or []),
                        )
                    else:
                        logger.warning(
                            "PDF %s: Yandex OCR не сконфигурирован, используем fallback.",
                            filename,
                        )
                except Exception as yv_err:
                    from app.services.yandex_vision_ocr import (
                        yandex_ocr_is_temporary,
                        yandex_ocr_quota_or_temporary_message,
                    )
                    yandex_rate_limited = yandex_ocr_is_temporary(yv_err)
                    logger.warning(
                        "PDF %s: Yandex OCR не удался (%s), используем fallback.",
                        filename,
                        yv_err,
                    )
                    if yandex_rate_limited:
                        logger.warning("PDF %s: %s", filename, yandex_ocr_quota_or_temporary_message(yv_err))

            # Fallback #1: native text layer via PyPDF
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name
            try:
                loader = PyPDFLoader(tmp_path)
                documents = loader.load()
                for doc in documents:
                    doc.metadata["source_file"] = filename
                    source = doc.metadata.get("source", "")
                    if source and "page" in source.lower():
                        try:
                            page_match = re.search(r"page[=:]?\s*(\d+)", source, re.IGNORECASE)
                            if page_match:
                                doc.metadata["source_page"] = int(page_match.group(1))
                        except Exception as e:
                            logger.debug("Could not extract page number from source '%s': %s", source, e)
                total_text = "".join((d.page_content or "").strip() for d in documents)
                if documents and total_text.strip():
                    logger.info("PDF %s: fallback PyPDFLoader, %s pages", filename, len(documents))
                    return documents
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)

            # Fallback #2: local Tesseract OCR
            ocr_docs = DocumentLoaderService._ocr_pdf(content, filename)
            if ocr_docs:
                return ocr_docs
            if yandex_rate_limited:
                raise ValueError(
                    "OCR временно недоступен из-за лимитов Yandex (429), а локальный OCR не настроен. "
                    "Повторите попытку позже или установите pytesseract/pymupdf."
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

                    if vision_api_configured():
                        pdf_bytes = xlsx_bytes_to_pdf_bytes(content)
                        docs = yandex_vision_ocr_pdf_documents_for_langchain(pdf_bytes, filename)
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
        elif ext == '.txt':
            return DocumentLoaderService.load_txt(content, filename)
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

