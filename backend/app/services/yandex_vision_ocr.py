"""Yandex Cloud Vision OCR — изображения и PDF (PDF бьём на части ≤ лимита страниц)."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Tuple

import requests

from app.config import config

logger = logging.getLogger(__name__)

VISION_BATCH_ANALYZE_URL = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"

# Доп. ограничение Yandex: размер файла OCR (ориентир ~10 МБ); при превышении — меньше страниц в чанке
YANDEX_VISION_PDF_BYTES_SOFT_LIMIT = 9 * 1024 * 1024


def vision_api_configured() -> bool:
    return bool(config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID)


def _extract_lines_from_text_detection(td: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for page in td.get("pages") or []:
        for block in page.get("blocks") or []:
            for line in block.get("lines") or []:
                parts: List[str] = []
                for word in line.get("words") or []:
                    t = word.get("text") or ""
                    if t:
                        parts.append(t)
                if parts:
                    lines.append(" ".join(parts))
    return lines


def _text_from_vision_page(page: Dict[str, Any]) -> str:
    lines_out: List[str] = []
    for block in page.get("blocks") or []:
        for line in block.get("lines") or []:
            parts: List[str] = []
            for word in line.get("words") or []:
                t = word.get("text") or ""
                if t:
                    parts.append(t)
            if parts:
                lines_out.append(" ".join(parts))
    return "\n".join(lines_out).strip()


def extract_text_from_vision_response(data: Dict[str, Any]) -> str:
    """Плоский текст из ответа batchAnalyze (для одного изображения)."""
    lines: List[str] = []
    for spec in data.get("results") or []:
        for inner in spec.get("results") or []:
            td = inner.get("textDetection") or inner.get("text_detection")
            if not td:
                continue
            lines.extend(_extract_lines_from_text_detection(td))
    return "\n".join(lines).strip()


def documents_from_vision_response(
    data: Dict[str, Any],
    *,
    page_offset: int,
    filename: str,
) -> List[Tuple[int, str]]:
    """
    Список (глобальный_номер_страницы_0_based, текст) из ответа Vision для PDF-чанка.
    """
    out: List[Tuple[int, str]] = []
    for spec in data.get("results") or []:
        for inner in spec.get("results") or []:
            td = inner.get("textDetection") or inner.get("text_detection")
            if not td:
                continue
            for i, page in enumerate(td.get("pages") or []):
                text = _text_from_vision_page(page)
                if text:
                    out.append((page_offset + i, text))
    return out


def _call_batch_analyze_base64(
    b64_content: str,
    *,
    timeout_sec: int,
) -> Dict[str, Any]:
    if not vision_api_configured():
        raise ValueError(
            "YANDEX_API_KEY и YANDEX_FOLDER_ID обязательны для Yandex Vision OCR."
        )

    body: Dict[str, Any] = {
        "folderId": config.YANDEX_FOLDER_ID,
        "analyze_specs": [
            {
                "content": b64_content,
                "features": [
                    {
                        "type": "TEXT_DETECTION",
                        "text_detection_config": {
                            "language_codes": ["ru", "en"],
                        },
                    }
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Api-Key {config.YANDEX_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        VISION_BATCH_ANALYZE_URL,
        data=json.dumps(body),
        headers=headers,
        timeout=timeout_sec,
    )
    if resp.status_code != 200:
        logger.error(
            "Yandex Vision OCR error: %s %s",
            resp.status_code,
            resp.text[:2000],
        )
        raise RuntimeError(
            f"Yandex Vision OCR вернул код {resp.status_code}. "
            f"Проверьте ключ API, каталог и роль ai.vision.user. Ответ: {resp.text[:500]}"
        )
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Yandex Vision: невалидный JSON: {e}") from e


def yandex_vision_recognize_text(
    image_bytes: bytes,
    *,
    timeout_sec: int = 120,
) -> str:
    """Одно изображение → текст."""
    b64 = base64.b64encode(image_bytes).decode("ascii")
    data = _call_batch_analyze_base64(b64, timeout_sec=timeout_sec)
    text = extract_text_from_vision_response(data)
    if not text:
        logger.warning("Yandex Vision OCR: пустой текст (возможно, нет текста на изображении).")
    return text


def _pdf_chunk_page_ranges(
    total_pages: int,
    max_pages: int,
    pdf_bytes_factory,
) -> List[Tuple[int, int]]:
    """
    Диапазоны [start, end) в страницах 0-based, чтобы каждый под-PDF не превышал max_pages
    и по возможности YANDEX_VISION_PDF_BYTES_SOFT_LIMIT.
    pdf_bytes_factory(start, end) -> bytes для проверки размера.
    """
    if total_pages <= 0 or max_pages <= 0:
        return []
    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < total_pages:
        end = min(start + max_pages, total_pages)
        # Уменьшаем end пока размер > soft limit (минимум 1 страница)
        while end > start + 1:
            chunk = pdf_bytes_factory(start, end)
            if len(chunk) <= YANDEX_VISION_PDF_BYTES_SOFT_LIMIT:
                break
            end = start + max(1, (end - start) // 2)
        ranges.append((start, end))
        start = end
    return ranges


def yandex_vision_ocr_pdf_bytes(content: bytes, filename: str) -> str:
    """
    Распознавание PDF целиком: несколько запросов к Vision по ≤ YANDEX_VISION_MAX_PDF_PAGES страниц.
    Возвращает один текст с маркерами страниц (для обратной совместимости с простым пайплайном).
    """
    docs = yandex_vision_ocr_pdf_to_page_documents(content, filename)
    if not docs:
        return ""
    parts: List[str] = []
    for page_idx, text in docs:
        parts.append(f"--- Стр. {page_idx + 1} ---\n{text}")
    return "\n\n".join(parts)


def yandex_vision_ocr_pdf_to_page_documents(content: bytes, filename: str) -> List[Tuple[int, str]]:
    """
    PDF → список (индекс_страницы_0_based, текст). Несколько вызовов API при > лимита страниц.
    """
    try:
        import fitz  # pymupdf
    except ImportError as e:
        raise RuntimeError(
            "Для OCR больших PDF нужен пакет pymupdf (import fitz). Установите: pip install pymupdf"
        ) from e

    if not vision_api_configured():
        raise ValueError("Yandex Vision: не заданы API ключ или каталог.")

    max_pages = max(1, int(getattr(config, "YANDEX_VISION_MAX_PDF_PAGES", 200) or 200))
    src = fitz.open(stream=content, filetype="pdf")
    try:
        total = len(src)
        if total == 0:
            return []

        def build_subpdf_bytes(p0: int, p1: int) -> bytes:
            sub = fitz.open()
            try:
                sub.insert_pdf(src, from_page=p0, to_page=p1 - 1)
                return sub.tobytes()
            finally:
                sub.close()

        ranges = _pdf_chunk_page_ranges(
            total,
            max_pages,
            lambda s, e: build_subpdf_bytes(s, e),
        )

        all_pages: List[Tuple[int, str]] = []

        for ri, (p0, p1) in enumerate(ranges):
            timeout = min(600, 90 + 45 * max(1, p1 - p0))
            chunk_bytes = build_subpdf_bytes(p0, p1)
            logger.info(
                "Yandex Vision PDF chunk %s/%s: pages %s–%s (%s bytes), file=%s",
                ri + 1,
                len(ranges),
                p0 + 1,
                p1,
                len(chunk_bytes),
                filename,
            )
            b64 = base64.b64encode(chunk_bytes).decode("ascii")
            data = _call_batch_analyze_base64(b64, timeout_sec=timeout)
            pairs = documents_from_vision_response(data, page_offset=p0, filename=filename)
            # Vision может вернуть меньше страниц, чем в чанке — заполняем пропуски пустыми не будем
            all_pages.extend(pairs)

        all_pages.sort(key=lambda x: x[0])
        return all_pages
    finally:
        src.close()


def yandex_vision_ocr_pdf_documents_for_langchain(content: bytes, filename: str):
    """Обёртка под langchain_core.documents.Document (ленивый import)."""
    from langchain_core.documents import Document

    pairs = yandex_vision_ocr_pdf_to_page_documents(content, filename)
    return [
        Document(
            page_content=text,
            metadata={
                "source_file": filename,
                "source_page": idx,
                "ocr": True,
                "ocr_engine": "yandex_vision_pdf",
            },
        )
        for idx, text in pairs
    ]
