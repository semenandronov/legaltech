"""File parsing utilities for Legal AI Vault"""
import os
from typing import Tuple
from pypdf import PdfReader
from docx import Document
import openpyxl


def _clean_text(text: str) -> str:
    """Remove NUL bytes and BOM markers"""
    if text is None:
        return ""
    return text.replace("\x00", "").replace("\ufeff", "")


def parse_pdf(file_content: bytes, filename: str) -> str:
    """Extract text from PDF file"""
    try:
        import io
        pdf_file = io.BytesIO(file_content)
        reader = PdfReader(pdf_file)
        text_parts = []
        for page in reader.pages:
            text_parts.append(page.extract_text())
        return _clean_text("\n".join(text_parts))
    except Exception as e:
        raise ValueError(f"Ошибка при чтении PDF файла {filename}: {str(e)}")


def parse_docx(file_content: bytes, filename: str) -> str:
    """Extract text from DOCX file"""
    try:
        import io
        import zipfile

        # Parse DOCX (python-docx library will validate the file format)
        docx_file = io.BytesIO(file_content)
        doc = Document(docx_file)
        text_parts = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)

        # Also extract text from tables
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    text_parts.append(row_text)

        result = _clean_text("\n".join(text_parts))
        if not result.strip():
            raise ValueError(f"DOCX файл {filename} не содержит текста")
        return result
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Ошибка при чтении DOCX файла {filename}: {str(e)}")


def parse_txt(file_content: bytes, filename: str) -> str:
    """Extract text from TXT file"""
    try:
        # Try different encodings
        for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
            try:
                return _clean_text(file_content.decode(encoding))
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Не удалось декодировать файл {filename}")
    except Exception as e:
        raise ValueError(f"Ошибка при чтении TXT файла {filename}: {str(e)}")


def _table_rows_to_text(headers: list, rows: list) -> list:
    """
    Convert table rows to text lines with column header context.
    Each row becomes: "Header1: Value1, Header2: Value2, ..."
    Empty cells are skipped. Fully empty rows are skipped.
    """
    text_lines = []
    for row in rows:
        parts = []
        for i, cell in enumerate(row):
            val = str(cell).strip() if cell is not None else ""
            if not val or val.lower() in ("none", "nan", "-"):
                continue
            header = headers[i] if i < len(headers) else f"Колонка{i + 1}"
            parts.append(f"{header}: {val}")
        if parts:
            text_lines.append(", ".join(parts))
    return text_lines


def parse_xlsx(file_content: bytes, filename: str) -> str:
    """
    Extract text from XLSX file.
    Each row is formatted as 'Header1: Value1, Header2: Value2, ...' so that
    column context is preserved after chunking.
    """
    try:
        import io
        xlsx_file = io.BytesIO(file_content)
        workbook = openpyxl.load_workbook(xlsx_file, data_only=True)
        text_parts = []

        for sheet_name in workbook.sheetnames:
            sheet = workbook[sheet_name]
            all_rows = list(sheet.iter_rows(values_only=True))
            if not all_rows:
                continue

            # Find the first non-empty row as the header
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

            text_parts.append(f"=== Лист: {sheet_name} ===")
            text_parts.extend(_table_rows_to_text(header_row, all_rows[data_start:]))

        result = _clean_text("\n".join(text_parts))
        if not result.strip():
            raise ValueError(f"XLSX файл {filename} не содержит данных")
        return result
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Ошибка при чтении XLSX файла {filename}: {str(e)}")


def parse_csv(file_content: bytes, filename: str) -> str:
    """
    Extract text from CSV file.
    Each row is formatted as 'Header1: Value1, Header2: Value2, ...' so that
    column context is preserved after chunking.
    """
    import csv
    import io

    # Try different encodings
    text = None
    for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
        try:
            text = file_content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError(f"Не удалось декодировать CSV файл {filename}")

    try:
        # Auto-detect delimiter (comma or semicolon)
        sample = text[:4096]
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel  # fallback: comma

    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        raise ValueError(f"CSV файл {filename} пуст")

    # First row = headers
    headers = [h.strip() if h.strip() else f"Колонка{i + 1}" for i, h in enumerate(rows[0])]
    text_lines = _table_rows_to_text(headers, rows[1:])

    result = _clean_text("\n".join(text_lines))
    if not result.strip():
        raise ValueError(f"CSV файл {filename} не содержит данных")
    return result


def parse_file(file_content: bytes, filename: str) -> str:
    """Parse file based on extension"""
    _, ext = os.path.splitext(filename.lower())

    if ext == ".pdf":
        return parse_pdf(file_content, filename)
    elif ext == ".docx":
        return parse_docx(file_content, filename)
    elif ext == ".txt":
        return parse_txt(file_content, filename)
    elif ext == ".xlsx":
        return parse_xlsx(file_content, filename)
    elif ext == ".csv":
        return parse_csv(file_content, filename)
    else:
        raise ValueError(f"Неподдерживаемый формат файла: {ext}")
