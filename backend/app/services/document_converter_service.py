"""Document Converter Service for Legal AI Vault"""
from typing import Dict, Optional, Any, Tuple
import logging
import io
import tempfile
import os
import re
import threading
from io import BytesIO
from app.config import config

logger = logging.getLogger(__name__)

# Minimal single-page PDF for startup warmup (loads Docling/MPS weights once).
_MINIMAL_WARMUP_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000052 00000 n \n"
    b"0000000101 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n178\n%%EOF"
)


class DocumentConverterService:
    """Service for converting documents to HTML format"""

    _instances: Dict[Tuple[str, bool], Any] = {}
    _lock = threading.Lock()
    
    def __init__(self):
        """Initialize document converter service"""
        pass
    
    def convert_to_html(
        self,
        file_content: bytes,
        filename: str,
        file_type: Optional[str] = None
    ) -> str:
        """
        Convert document to HTML format
        
        Args:
            file_content: File content as bytes
            filename: Original filename
            file_type: File type/extension (optional, will be inferred from filename)
            
        Returns:
            HTML string representation of the document
            
        Raises:
            ValueError: If file format is not supported or conversion fails
        """
        if not file_content:
            raise ValueError("File content is empty")
        
        # Determine file type from filename if not provided
        if not file_type:
            _, ext = os.path.splitext(filename)
            file_type = ext.lower().lstrip('.')
        
        logger.info(f"Converting {filename} (type: {file_type}) to HTML")
        
        try:
            # Route to appropriate converter based on file type
            if file_type in ['docx', 'doc']:
                return self._convert_docx(file_content)
            elif file_type == 'pdf':
                return self._convert_pdf(file_content)
            elif file_type in ['xlsx', 'xls', 'xlsm']:
                return self._convert_xlsx(file_content, filename)
            elif file_type == 'txt':
                return self._convert_txt(file_content)
            elif file_type in ['pptx', 'ppt']:
                return self._convert_with_markitdown(file_content, filename)
            else:
                # Try universal converter for other formats
                logger.warning(f"Unknown file type {file_type}, trying universal converter")
                return self._convert_with_markitdown(file_content, filename)
        except Exception as e:
            logger.error(f"Error converting {filename} to HTML: {e}", exc_info=True)
            raise ValueError(f"Не удалось конвертировать файл {filename}: {str(e)}")
    
    def _convert_docx(self, file_content: bytes) -> str:
        """
        Convert DOCX to HTML using mammoth
        
        Args:
            file_content: DOCX file content as bytes
            
        Returns:
            HTML string
        """
        try:
            import mammoth
            
            # Convert DOCX to HTML
            result = mammoth.convert_to_html(BytesIO(file_content))
            html = result.value
            
            # Log warnings if any
            if result.messages:
                logger.warning(f"Mammoth conversion warnings: {result.messages}")
            
            # Wrap in a container div for consistent styling
            html = f'<div class="docx-content">{html}</div>'
            
            logger.info("Successfully converted DOCX to HTML")
            return html
        except ImportError:
            logger.error("mammoth library not installed")
            raise ValueError("Библиотека для конвертации DOCX не установлена")
        except Exception as e:
            logger.error(f"Error converting DOCX: {e}", exc_info=True)
            raise ValueError(f"Ошибка конвертации DOCX: {str(e)}")
    
    def _convert_pdf(self, file_content: bytes) -> str:
        """
        PDF → HTML: сначала Docling (структура, таблицы, лучше для сложных макетов),
        при ошибке или пустом результате — pypdf.
        Docling: https://github.com/docling-project/docling
        """
        try:
            return self._convert_pdf_docling(file_content)
        except Exception as e:
            logger.warning("Docling PDF conversion failed, using pypdf fallback: %s", e)
            return self._convert_pdf_pypdf(file_content)

    @staticmethod
    def _build_pdf_pipeline_options(*, do_ocr: bool = True) -> Optional[Any]:
        """
        Единые PdfPipelineOptions для HTML-редактора, LegalChunkerV2 и preflight OCR в DocumentLoaderService.

        do_ocr=False: только текстовый слой PDF + layout/таблицы (для PDF с native text, без повторного OCR).
        """
        try:
            from docling.datamodel.pipeline_options import (
                PdfPipelineOptions,
                TableFormerMode,
                EasyOcrOptions,
                TesseractCliOcrOptions,
            )
        except Exception as exc:
            logger.debug("Docling PdfPipelineOptions import failed: %s", exc)
            return None

        pipeline_options = PdfPipelineOptions(
            do_table_structure=bool(getattr(config, "DOCLING_PDF_TABLE_STRUCTURE", True)),
            do_ocr=bool(do_ocr),
            enable_remote_services=bool(getattr(config, "DOCLING_ENABLE_REMOTE_SERVICES", False)),
        )
        if not do_ocr:
            artifacts_path = str(getattr(config, "DOCLING_ARTIFACTS_PATH", "") or "").strip()
            if artifacts_path:
                pipeline_options.artifacts_path = artifacts_path
            return pipeline_options

        engine = str(getattr(config, "DOCLING_PDF_OCR_ENGINE", "auto") or "auto").strip().lower()
        if engine in ("docling_easyocr",):
            engine = "easyocr"
        table_opts = getattr(pipeline_options, "table_structure_options", None)
        if table_opts is not None:
            table_opts.do_cell_matching = bool(
                getattr(config, "DOCLING_PDF_TABLE_CELL_MATCHING", True)
            )
            mode_name = str(getattr(config, "DOCLING_PDF_TABLE_MODE", "accurate")).upper()
            if hasattr(TableFormerMode, mode_name):
                table_opts.mode = getattr(TableFormerMode, mode_name)

        force_fp = bool(getattr(config, "DOCLING_OCR_FORCE_FULL_PAGE", False))
        bitmap_thr = float(getattr(config, "DOCLING_OCR_BITMAP_AREA_THRESHOLD", 0.05) or 0.05)

        if engine == "easyocr":
            raw = str(getattr(config, "DOCLING_OCR_EASYOCR_LANGS", "ru,en") or "ru,en")
            ez_langs = [p.strip() for p in raw.split(",") if p.strip()]
            if not ez_langs:
                ez_langs = ["ru", "en"]
            pipeline_options.ocr_options = EasyOcrOptions(
                lang=ez_langs,
                force_full_page_ocr=force_fp,
                bitmap_area_threshold=bitmap_thr,
            )
        elif engine in ("tesseract_cli", "tesseract"):
            raw = str(getattr(config, "DOCLING_OCR_TESSERACT_LANGS", "rus,eng") or "rus,eng")
            tess_langs = [p.strip() for p in raw.replace("+", ",").split(",") if p.strip()]
            if not tess_langs:
                tess_langs = ["rus", "eng"]
            pipeline_options.ocr_options = TesseractCliOcrOptions(
                lang=tess_langs,
                force_full_page_ocr=force_fp,
                bitmap_area_threshold=bitmap_thr,
            )
        else:
            ocr_opts = getattr(pipeline_options, "ocr_options", None)
            if ocr_opts is not None:
                ocr_opts.force_full_page_ocr = force_fp
                ocr_opts.bitmap_area_threshold = bitmap_thr
                langs = list(getattr(config, "DOCLING_OCR_LANGUAGES", []) or [])
                if langs:
                    try:
                        ocr_opts.lang = langs
                    except Exception:
                        logger.debug("DOCLING_OCR_LANGUAGES не применимы к текущему auto OCR", exc_info=True)

        artifacts_path = str(getattr(config, "DOCLING_ARTIFACTS_PATH", "") or "").strip()
        if artifacts_path:
            pipeline_options.artifacts_path = artifacts_path

        return pipeline_options

    @staticmethod
    def _converter_cache_key(ext: str, *, do_ocr: bool) -> Tuple[str, bool]:
        normalized = (ext or "").strip().lower()
        if normalized and not normalized.startswith("."):
            normalized = f".{normalized}"
        return (normalized, bool(do_ocr))

    @classmethod
    def _create_converter_instance(cls, ext: str, *, do_ocr: bool) -> Optional[Any]:
        if ext == ".pdf":
            return cls._build_docling_pdf_converter(do_ocr=do_ocr)
        try:
            from docling.document_converter import DocumentConverter

            return DocumentConverter()
        except Exception as exc:
            logger.debug("Docling DocumentConverter unavailable for %s: %s", ext, exc)
            return None

    @classmethod
    def get_cached_converter(cls, ext: str, *, do_ocr: bool = True) -> Optional[Any]:
        """Process-wide cached DocumentConverter (keyed by extension + OCR mode)."""
        key = cls._converter_cache_key(ext, do_ocr=do_ocr)
        cached = cls._instances.get(key)
        if cached is not None:
            return cached

        with cls._lock:
            cached = cls._instances.get(key)
            if cached is not None:
                return cached
            instance = cls._create_converter_instance(key[0], do_ocr=key[1])
            if instance is None:
                return None
            cls._instances[key] = instance
            logger.info(
                "[Docling] Initialized cached converter ext=%s do_ocr=%s",
                key[0],
                key[1],
            )
            return instance

    @classmethod
    def reset_converter_cache_for_tests(cls) -> None:
        """Drop cached converters (unit tests only)."""
        with cls._lock:
            cls._instances.clear()

    @classmethod
    def warmup(cls) -> bool:
        """Pre-warm Docling models at application startup (native PDF path)."""
        if not bool(getattr(config, "DOCLING_WARMUP_ON_STARTUP", True)):
            logger.info("Docling warmup skipped (DOCLING_WARMUP_ON_STARTUP=false)")
            return False

        converter = cls.get_cached_converter(".pdf", do_ocr=False)
        if converter is None:
            logger.warning("Docling warmup skipped: converter unavailable")
            return False

        try:
            cls._run_warmup_convert(converter)
            logger.info("Docling warmup ok (pdf, do_ocr=False, convert completed)")
        except Exception as exc:
            logger.warning(
                "Docling warmup convert failed (converter still cached): %s",
                exc,
                exc_info=True,
            )
        return True

    @staticmethod
    def _run_warmup_convert(converter: Any) -> None:
        from docling.datamodel.base_models import DocumentStream

        pdf_bytes = _MINIMAL_WARMUP_PDF_BYTES
        source = DocumentStream(name="warmup.pdf", stream=BytesIO(pdf_bytes))
        try:
            converter.convert(
                source=source,
                max_num_pages=1,
                max_file_size=max(len(pdf_bytes), 1),
            )
        except TypeError:
            converter.convert(source=source)
        finally:
            source.stream.close()

    @staticmethod
    def extract_pdf_text_via_docling(content: bytes, filename: str) -> str:
        """
        Один проход Docling по PDF → markdown (OCR внутри Docling).

        Не используется в ingest-пайплайне сканов: для них — Yandex OCR → LegalChunkerV2
        без повторного Docling. Оставлен для явных вызовов вне file ingest.
        """
        converter = DocumentConverterService.get_cached_converter(".pdf", do_ocr=True)
        if converter is None:
            raise RuntimeError("Docling недоступен (конвертер не инициализирован)")

        from docling.datamodel.base_models import DocumentStream
        safe_name = (filename or "document.pdf").replace("\\", "/").split("/")[-1] or "document.pdf"
        source = DocumentStream(name=safe_name, stream=BytesIO(content))
        max_pages = max(1, int(getattr(config, "DOCLING_MAX_PAGES_PER_DOC", 2000) or 2000))
        max_file_size = max(
            1,
            int(getattr(config, "DOCLING_MAX_FILE_SIZE_BYTES", 60 * 1024 * 1024) or 60 * 1024 * 1024),
        )
        try:
            logger.info(
                "Docling PDF preflight OCR start (%s bytes, engine=%s); затем чанкер выполнит второй проход Docling",
                len(content or b""),
                str(getattr(config, "DOCLING_PDF_OCR_ENGINE", "auto") or "auto"),
            )
            result = converter.convert(
                source=source,
                max_num_pages=max_pages,
                max_file_size=max_file_size,
            )
            doc = result.document
            exporter = getattr(doc, "export_to_markdown", None)
            md = exporter() if callable(exporter) else ""
            return (md or "").strip()
        finally:
            source.stream.close()

    @staticmethod
    def _build_docling_pdf_converter(*, do_ocr: bool = True) -> Optional[Any]:
        """
        Build tuned Docling converter for PDF->HTML editor rendering.
        Falls back to default converter if advanced options are unavailable.
        """
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except Exception:
            return None

        pipeline_options = DocumentConverterService._build_pdf_pipeline_options(do_ocr=do_ocr)
        if pipeline_options is None:
            return None

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

    def _convert_pdf_docling(self, file_content: bytes) -> str:
        """Конвертация PDF через Docling (export_to_html или markdown → HTML)."""
        from docling.datamodel.base_models import DocumentStream
        from docling.document_converter import DocumentConverter

        if not file_content:
            raise ValueError("File content is empty")

        converter = DocumentConverterService.get_cached_converter(".pdf", do_ocr=True)
        if converter is None:
            converter = DocumentConverter()
        max_pages = max(1, int(getattr(config, "DOCLING_MAX_PAGES_PER_DOC", 300) or 300))
        max_file_size = max(
            1,
            int(getattr(config, "DOCLING_MAX_FILE_SIZE_BYTES", 60 * 1024 * 1024) or 60 * 1024 * 1024),
        )
        source = DocumentStream(name="editor.pdf", stream=BytesIO(file_content))
        result = converter.convert(
            source=source,
            max_num_pages=max_pages,
            max_file_size=max_file_size,
        )
        try:
            doc = result.document

            html_body: Optional[str] = None
            if hasattr(doc, "export_to_html"):
                try:
                    html_body = doc.export_to_html()
                except Exception as ex:
                    logger.debug("Docling export_to_html failed: %s", ex)
            if not html_body or not str(html_body).strip():
                import markdown as md_lib

                md_text = doc.export_to_markdown()
                if not md_text or not md_text.strip():
                    raise ValueError("Docling returned empty document")
                html_body = md_lib.markdown(md_text, extensions=["extra", "nl2br"])

            inner = str(html_body).strip()
            # Полный HTML-документ от Docling — оставляем как есть в обёртке для единообразия селекторов
            if inner.lower().startswith("<!doctype") or (
                inner.lower().startswith("<html") and "</html>" in inner.lower()
            ):
                wrapped = f'<div class="pdf-content pdf-content--docling">{inner}</div>'
            else:
                wrapped = f'<div class="pdf-content pdf-content--docling">{inner}</div>'

            logger.info("Successfully converted PDF to HTML via Docling")
            return wrapped
        finally:
            source.stream.close()

    def _convert_pdf_pypdf(self, file_content: bytes) -> str:
        """
        Convert PDF to HTML using pypdf with improved paragraph detection.

        pypdf returns text with single \\n between lines (not double \\n),
        so splitting by \\n\\n rarely works. Instead we group lines into
        paragraphs using sentence-boundary heuristics.
        """
        try:
            from pypdf import PdfReader

            pdf_reader = PdfReader(BytesIO(file_content))
            html_parts = ['<div class="pdf-content">']

            for page_num, page in enumerate(pdf_reader.pages, 1):
                try:
                    text = page.extract_text()
                    if not text:
                        continue

                    html_parts.append(f'<div class="pdf-page" data-page="{page_num}">')

                    raw_lines = text.split('\n')
                    paragraphs = self._group_pdf_lines(raw_lines)

                    for para in paragraphs:
                        if para.strip():
                            # Escape stray HTML in extracted text
                            safe = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            html_parts.append(f'<p>{safe}</p>')

                    html_parts.append('</div>')

                except Exception as e:
                    logger.warning(f"Error extracting text from page {page_num}: {e}")
                    html_parts.append(
                        f'<div class="pdf-page" data-page="{page_num}">'
                        f'<p>Не удалось извлечь текст со страницы {page_num}</p></div>'
                    )

            html_parts.append('</div>')
            html = '\n'.join(html_parts)

            if html == '<div class="pdf-content">\n</div>':
                raise ValueError("Не удалось извлечь текст из PDF файла")

            logger.info(f"Successfully converted PDF to HTML via pypdf ({len(pdf_reader.pages)} pages)")
            return html

        except ImportError:
            logger.error("pypdf library not installed")
            raise ValueError("Библиотека для конвертации PDF не установлена")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error converting PDF: {e}", exc_info=True)
            raise ValueError(f"Ошибка конвертации PDF: {str(e)}")

    @staticmethod
    def _group_pdf_lines(raw_lines: list) -> list:
        """
        Group raw PDF text lines into logical paragraphs.

        pypdf extracts text line-by-line without reliable paragraph markers.
        Heuristics used:
          - Empty line  → paragraph break
          - Line ending in sentence-terminal punctuation (.!?:;)
            followed by a line that starts with an uppercase letter or digit
            → paragraph break (next line starts a new paragraph)
          - Otherwise   → lines are joined with a space
        """
        SENTENCE_END = frozenset('.!?;:»)')
        paragraphs: list = []
        current: list = []

        def flush():
            if current:
                paragraphs.append(' '.join(current))
                current.clear()

        for line in raw_lines:
            stripped = line.strip()

            # Empty line is an explicit paragraph separator
            if not stripped:
                flush()
                continue

            if current:
                prev = current[-1]
                # Detect sentence boundary: previous line ends with terminal punctuation
                # and this line starts a new "unit" (uppercase / digit)
                prev_ends_sentence = prev and prev[-1] in SENTENCE_END
                line_starts_new = stripped and (stripped[0].isupper() or stripped[0].isdigit())

                if prev_ends_sentence and line_starts_new:
                    flush()

            current.append(stripped)

        flush()
        return paragraphs
    
    def _convert_xlsx(self, file_content: bytes, filename: str) -> str:
        """
        Convert XLSX/XLS to HTML using openpyxl for in-app preview + citation highlight.
        """
        try:
            import openpyxl
            from datetime import date, datetime

            workbook = openpyxl.load_workbook(BytesIO(file_content), data_only=True)

            def _fmt_cell(value: Any) -> str:
                if value is None:
                    return ""
                if isinstance(value, datetime):
                    return value.strftime("%d.%m.%Y")
                if isinstance(value, date):
                    return value.strftime("%d.%m.%Y")
                if isinstance(value, float) and value.is_integer():
                    return str(int(value))
                if isinstance(value, float):
                    return f"{value:.2f}"
                return str(value)

            html_parts = [
                '<div class="xlsx-content">',
                "<style>"
                ".xlsx-content{font-family:inherit;font-size:13px;line-height:1.45}"
                ".xlsx-sheet{margin-bottom:1.5rem;overflow-x:auto}"
                ".sheet-name{margin:0 0 .75rem;font-size:1rem;font-weight:600}"
                ".xlsx-table{border-collapse:collapse;width:100%;min-width:480px}"
                ".xlsx-table th,.xlsx-table td{border:1px solid #d0d5dd;padding:6px 8px;"
                "text-align:left;vertical-align:top;white-space:pre-wrap}"
                ".xlsx-table th{background:#f2f4f7;font-weight:600}"
                ".xlsx-table tr[data-row]:hover{background:#f9fafb}"
                ".xlsx-table tr.citation-row-highlight,"
                ".xlsx-table tr.citation-row-highlight td,"
                ".xlsx-table tr.citation-row-highlight th{"
                "background:#fef08a!important;outline:2px solid #eab308}"
                "</style>",
            ]

            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]

                html_parts.append('<div class="xlsx-sheet">')
                html_parts.append(f'<h3 class="sheet-name">{sheet_name}</h3>')
                html_parts.append('<table class="xlsx-table">')

                if sheet.max_row == 0 or sheet.max_column == 0:
                    html_parts.append('<tr><td colspan="1">Пустой лист</td></tr>')
                else:
                    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
                        cells = [_fmt_cell(v) for v in row]
                        fingerprint = "|".join(c for c in cells if c)[:120]
                        safe_fp = (
                            fingerprint.replace("&", "&amp;")
                            .replace('"', "&quot;")
                            .replace("<", "&lt;")
                            .replace(">", "&gt;")
                        )
                        html_parts.append(
                            f'<tr data-row="{row_idx}" data-row-key="{safe_fp}">'
                        )
                        for cell_html in cells:
                            cell_escaped = (
                                cell_html.replace("&", "&amp;")
                                .replace("<", "&lt;")
                                .replace(">", "&gt;")
                            )
                            tag = "th" if row_idx == 1 else "td"
                            html_parts.append(f"<{tag}>{cell_escaped}</{tag}>")
                        html_parts.append("</tr>")

                html_parts.append("</table>")
                html_parts.append("</div>")

            html_parts.append("</div>")
            html = "\n".join(html_parts)

            logger.info(
                "Successfully converted XLSX to HTML (%s sheets)",
                len(workbook.sheetnames),
            )
            return html
        except ImportError:
            logger.error("openpyxl library not installed")
            raise ValueError("Библиотека для конвертации Excel не установлена")
        except Exception as e:
            logger.error(f"Error converting XLSX: {e}", exc_info=True)
            raise ValueError(f"Ошибка конвертации Excel: {str(e)}")
    
    def _convert_txt(self, file_content: bytes) -> str:
        """
        Convert TXT to HTML
        
        Args:
            file_content: Text file content as bytes
            
        Returns:
            HTML string
        """
        try:
            # Try UTF-8 first, fallback to other encodings
            try:
                text = file_content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text = file_content.decode('windows-1251')
                except UnicodeDecodeError:
                    text = file_content.decode('latin-1', errors='ignore')
            
            # Split into paragraphs (double newlines)
            paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
            
            if not paragraphs:
                # If no double newlines, split by single newlines
                paragraphs = [p.strip() for p in text.split('\n') if p.strip()]
            
            html_parts = ['<div class="txt-content">']
            
            for para in paragraphs:
                # Replace single newlines with <br> within paragraphs
                para_html = para.replace('\n', '<br/>')
                # Escape HTML special characters
                para_html = para_html.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                html_parts.append(f'<p>{para_html}</p>')
            
            html_parts.append('</div>')
            
            html = '\n'.join(html_parts)
            
            logger.info("Successfully converted TXT to HTML")
            return html
        except Exception as e:
            logger.error(f"Error converting TXT: {e}", exc_info=True)
            raise ValueError(f"Ошибка конвертации TXT: {str(e)}")
    
    def _convert_with_markitdown(
        self,
        file_content: bytes,
        filename: str
    ) -> str:
        """
        Convert document to HTML using markitdown (universal converter)
        
        Args:
            file_content: File content as bytes
            filename: Original filename
            
        Returns:
            HTML string
        """
        try:
            from markitdown import MarkItDown
            import markdown
            
            # Save to temporary file for markitdown
            _, ext = os.path.splitext(filename)
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
                tmp_file.write(file_content)
                tmp_path = tmp_file.name
            
            try:
                # Convert using markitdown
                md = MarkItDown()
                result = md.convert(tmp_path)
                
                # Get markdown content
                markdown_content = result.text_content
                
                # Convert markdown to HTML
                html = markdown.markdown(markdown_content, extensions=['extra', 'nl2br'])
                
                # Wrap in container
                html = f'<div class="markitdown-content">{html}</div>'
                
                logger.info(f"Successfully converted {filename} to HTML using markitdown")
                return html
            finally:
                # Clean up temp file
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        except ImportError:
            logger.warning("markitdown or markdown library not installed, falling back to basic conversion")
            # Fallback: try to extract text and wrap in HTML
            try:
                text = file_content.decode('utf-8', errors='ignore')
                html = f'<div class="fallback-content"><pre>{text}</pre></div>'
                return html
            except Exception as e:
                logger.error(f"Fallback conversion failed: {e}", exc_info=True)
                raise ValueError(f"Не удалось конвертировать файл {filename}: формат не поддерживается")
        except Exception as e:
            logger.error(f"Error converting with markitdown: {e}", exc_info=True)
            # Fallback to basic text extraction
            try:
                text = file_content.decode('utf-8', errors='ignore')
                html = f'<div class="fallback-content"><pre>{text}</pre></div>'
                logger.warning(f"Used fallback conversion for {filename}")
                return html
            except Exception as fallback_error:
                logger.error(f"Fallback conversion also failed: {fallback_error}", exc_info=True)
                raise ValueError(f"Не удалось конвертировать файл {filename}: {str(e)}")

