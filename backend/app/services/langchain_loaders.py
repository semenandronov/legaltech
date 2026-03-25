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
        Load PDF document using PyPDFLoader with OCR fallback for scanned PDFs.
        """
        try:
            # Save to temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name

            try:
                loader = PyPDFLoader(tmp_path)
                documents = loader.load()

                # Add filename and page info to metadata
                for doc in documents:
                    doc.metadata["source_file"] = filename
                    source = doc.metadata.get("source", "")
                    if source and "page" in source.lower():
                        try:
                            page_match = re.search(r'page[=:]?\s*(\d+)', source, re.IGNORECASE)
                            if page_match:
                                doc.metadata["source_page"] = int(page_match.group(1))
                        except Exception as e:
                            logger.debug(f"Could not extract page number from source '{source}': {e}")

                # Check if extracted text is meaningful (scanned PDFs return near-empty text)
                total_text = "".join(doc.page_content.strip() for doc in documents)
                if len(total_text) < 50 and len(documents) > 0:
                    logger.info(
                        f"PDF {filename} has {len(documents)} pages but only {len(total_text)} chars of text. "
                        f"Attempting OCR for scanned PDF..."
                    )
                    ocr_docs = DocumentLoaderService._ocr_pdf(content, filename)
                    if ocr_docs:
                        return ocr_docs

                logger.info(f"Loaded PDF {filename}: {len(documents)} pages")
                return documents
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
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
    def load_xlsx(content: bytes, filename: str) -> List[Document]:
        """
        Load Excel document (convert to text format).
        Each data row is formatted as 'Header1: Value1, Header2: Value2, ...' so
        column context is preserved. Merged cells are forward-filled so every row
        carries the correct month/category label.
        """
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(io.BytesIO(content), data_only=True)
            documents = []

            for sheet_name in workbook.sheetnames:
                sheet = workbook[sheet_name]
                all_rows = list(sheet.iter_rows(values_only=True))
                if not all_rows:
                    continue

                # Find first non-empty row as header
                header_row = None
                data_start = 0
                for i, row in enumerate(all_rows):
                    if any(cell is not None and str(cell).strip() for cell in row):
                        header_row = [
                            str(cell).strip() if (cell is not None and str(cell).strip()) else f"Колонка{j + 1}"
                            for j, cell in enumerate(row)
                        ]
                        data_start = i + 1
                        break

                if header_row is None:
                    continue

                # Forward-fill None values column-by-column to handle merged cells
                filled_rows: List[list] = []
                last_values: list = [None] * len(header_row)
                for row in all_rows[data_start:]:
                    new_row = list(row)
                    for j in range(len(new_row)):
                        if new_row[j] is None:
                            new_row[j] = last_values[j]
                        else:
                            last_values[j] = new_row[j]
                    filled_rows.append(new_row)

                # Format each row as "Header: Value, ..."
                text_lines = [f"=== Лист: {sheet_name} ==="]
                for row in filled_rows:
                    parts = []
                    for j, cell in enumerate(row):
                        val = str(cell).strip() if cell is not None else ""
                        if not val or val.lower() in ("none", "nan", "-"):
                            continue
                        header = header_row[j] if j < len(header_row) else f"Колонка{j + 1}"
                        parts.append(f"{header}: {val}")
                    if parts:
                        text_lines.append(", ".join(parts))

                sheet_text = "\n".join(text_lines)
                if sheet_text.strip():
                    documents.append(Document(
                        page_content=sheet_text,
                        metadata={"source_file": filename, "sheet_name": sheet_name, "source_type": "excel"},
                    ))

            logger.info(f"Loaded XLSX {filename}: {len(documents)} sheets")
            return documents
        except Exception as e:
            logger.error(f"Error loading XLSX {filename}: {e}", exc_info=True)
            raise
    
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
        else:
            raise ValueError(f"Unsupported file format: {ext}")

