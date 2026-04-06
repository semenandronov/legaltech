"""Yandex Cloud Vision OCR for images and PDF."""
from __future__ import annotations

import base64
import json
import logging
import os
import random
import threading
import time
import uuid
from typing import Any, Dict, List, Sequence, Tuple

import requests

from app.config import config

logger = logging.getLogger(__name__)

VISION_BATCH_ANALYZE_URL = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"

# New OCR API (supports model selection: page, table, handwritten, markdown, etc.)
VISION_OCR_RECOGNIZE_TEXT_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
VISION_OCR_RECOGNIZE_TEXT_ASYNC_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeTextAsync"
VISION_OCR_GET_RECOGNITION_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/getRecognition"

# Service limits:
# Old batchAnalyze: gRPC body limit = 4 MB. Base64 adds ~33% overhead,
# so raw PDF chunk must stay under 3 MB (3 MB * 1.33 ≈ 4 MB base64).
# New OCR API: HTTP, limit = 10 MB raw.
YANDEX_VISION_PDF_BYTES_SOFT_LIMIT = 3 * 1024 * 1024   # 3 MB for old batchAnalyze
YANDEX_VISION_IMAGE_BYTES_SOFT_LIMIT = 9 * 1024 * 1024  # images use new API, 10 MB ok
YANDEX_VISION_MAX_RETRIES = 3
YANDEX_VISION_MIN_REQUEST_INTERVAL_SEC = 1.1
YANDEX_VISION_LANGUAGE_CODES = ("ru", "en")

_request_gate_lock = threading.Lock()
_last_request_monotonic = 0.0


class YandexOCRTemporaryError(RuntimeError):
    """Temporary upstream issue (rate limit, transient server/network)."""


class YandexOCRQuotaError(YandexOCRTemporaryError):
    """Rate-limit / quota exceeded."""


def vision_api_configured() -> bool:
    return bool(config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID)


def _wait_rate_limit() -> None:
    """Process-level pacing to reduce 429 under upload bursts."""
    global _last_request_monotonic
    min_interval = float(getattr(config, "YANDEX_OCR_MIN_REQUEST_INTERVAL_SEC", YANDEX_VISION_MIN_REQUEST_INTERVAL_SEC))
    with _request_gate_lock:
        now = time.monotonic()
        wait_for = min_interval - (now - _last_request_monotonic)
        if wait_for > 0:
            time.sleep(wait_for)
        _last_request_monotonic = time.monotonic()


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
    language_codes: Sequence[str] = YANDEX_VISION_LANGUAGE_CODES,
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
                            "language_codes": list(language_codes),
                        },
                    }
                ],
            }
        ],
    }
    max_retries = max(1, int(getattr(config, "YANDEX_OCR_MAX_RETRIES", YANDEX_VISION_MAX_RETRIES) or YANDEX_VISION_MAX_RETRIES))
    headers = {
        "Authorization": f"Api-Key {config.YANDEX_API_KEY}",
        "Content-Type": "application/json",
        "x-client-request-id": str(uuid.uuid4()),
        "x-data-logging-enabled": "true" if getattr(config, "YANDEX_OCR_DATA_LOGGING_ENABLED", True) else "false",
    }
    last_err: str | None = None
    for attempt in range(1, max_retries + 1):
        _wait_rate_limit()
        try:
            resp = requests.post(
                VISION_BATCH_ANALYZE_URL,
                data=json.dumps(body),
                headers=headers,
                timeout=timeout_sec,
            )
        except requests.RequestException as exc:
            last_err = str(exc)
            if attempt < max_retries:
                sleep_s = min(8.0, (2 ** (attempt - 1)) + random.uniform(0.0, 0.5))
                logger.warning(
                    "Yandex Vision OCR network error (attempt %s/%s): %s. Retry in %ss.",
                    attempt,
                    max_retries,
                    exc,
                    sleep_s,
                )
                time.sleep(sleep_s)
                continue
            raise YandexOCRTemporaryError(f"Yandex Vision OCR network error: {exc}") from exc

        if resp.status_code == 200:
            req_id = resp.headers.get("x-request-id")
            trace_id = resp.headers.get("x-server-trace-id")
            if req_id or trace_id:
                logger.info(
                    "Yandex OCR response headers: x-request-id=%s x-server-trace-id=%s",
                    req_id,
                    trace_id,
                )
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Yandex Vision: невалидный JSON: {e}") from e
            for outer in data.get("results") or []:
                if isinstance(outer, dict) and outer.get("error"):
                    err = outer.get("error") or {}
                    code = err.get("code")
                    msg = str(err.get("message") or "")
                    if str(code) == "8":
                        # gRPC RESOURCE_EXHAUSTED: could be quota OR message-too-large
                        if "larger than max" in msg or "message larger" in msg:
                            raise ValueError(
                                f"Yandex OCR: PDF-чанк слишком большой для API ({msg}). "
                                "Размер чанка автоматически уменьшится при следующем запросе."
                            )
                        raise YandexOCRQuotaError(f"Yandex OCR quota exceeded: {msg}")
                    if str(code) in {"13"}:
                        raise YandexOCRTemporaryError(f"Yandex OCR temporary server error: {msg}")
                    if str(code) == "3":
                        raise ValueError(f"Yandex OCR bad file/config: {msg}")
            return data

        last_err = f"{resp.status_code}: {resp.text[:500]}"
        req_id = resp.headers.get("x-request-id")
        trace_id = resp.headers.get("x-server-trace-id")
        retryable = resp.status_code in (408, 429, 500, 502, 503, 504)
        if retryable and attempt < max_retries:
            retry_after = resp.headers.get("Retry-After")
            backoff = 2 ** attempt
            try:
                backoff = max(backoff, float(retry_after)) if retry_after else backoff
            except ValueError:
                pass
            sleep_s = min(20.0, backoff + random.uniform(0.0, 0.7))
            logger.warning(
                "Yandex Vision OCR temporary error (attempt %s/%s): %s; req=%s trace=%s. Retry in %ss.",
                attempt,
                max_retries,
                last_err,
                req_id,
                trace_id,
                sleep_s,
            )
            time.sleep(sleep_s)
            continue

        logger.error("Yandex Vision OCR error: %s; req=%s trace=%s", last_err, req_id, trace_id)
        if resp.status_code == 429:
            # 429 can also mean "message too large" wrapped in HTTP 429 by Yandex proxy
            if "larger than max" in resp.text or "message larger" in resp.text:
                raise ValueError(
                    f"Yandex OCR: PDF-чанк слишком большой для API. "
                    f"req={req_id}. Уменьшите размер файла или дождитесь обновления."
                )
            raise YandexOCRQuotaError(
                f"Yandex Vision OCR rate limited (429). req={req_id} trace={trace_id}."
            )
        if resp.status_code in (408, 500, 502, 503, 504):
            raise YandexOCRTemporaryError(
                f"Yandex Vision OCR temporary error {resp.status_code}. req={req_id} trace={trace_id}."
            )
        raise RuntimeError(
            f"Yandex Vision OCR вернул код {resp.status_code}. "
            f"Проверьте ключ API, каталог и роль ai.vision.user. Ответ: {resp.text[:500]}"
        )

    raise YandexOCRTemporaryError(
        f"Yandex Vision OCR failed after retries: {last_err or 'unknown error'}"
    )


def normalize_image_for_yandex(image_bytes: bytes, filename: str = "") -> bytes:
    """
    Нормализует изображение к PNG для форматов вне JPEG/PNG.
    Это повышает стабильность OCR для WEBP/BMP/TIFF/GIF.
    """
    _, ext = os.path.splitext((filename or "").lower())
    if ext in (".jpg", ".jpeg", ".png"):
        if len(image_bytes) <= YANDEX_VISION_IMAGE_BYTES_SOFT_LIMIT:
            return image_bytes
        # Too large JPEG/PNG: try to recompress to fit OCR limit.
        ext = ".jpg"
    else:
        ext = ".png"

    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Для нормализации изображений нужен Pillow (pip install pillow)."
        ) from e

    from io import BytesIO

    with Image.open(BytesIO(image_bytes)) as img:
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Keep 20MP max and try iterative compression for <= ~9MB payload.
        max_px = 20_000_000
        width, height = img.size
        if width * height > max_px:
            ratio = (max_px / float(width * height)) ** 0.5
            img = img.resize((max(1, int(width * ratio)), max(1, int(height * ratio))))

        for quality in (90, 80, 70, 60):
            out = BytesIO()
            if ext == ".png":
                img.save(out, format="PNG", optimize=True)
            else:
                img.save(out, format="JPEG", quality=quality, optimize=True)
            payload = out.getvalue()
            if len(payload) <= YANDEX_VISION_IMAGE_BYTES_SOFT_LIMIT:
                return payload
        # Return best effort if still large; API may reject and we'll surface that clearly.
        out = BytesIO()
        img.save(out, format="JPEG", quality=55, optimize=True)
        return out.getvalue()

    # Unreachable fallback
    return image_bytes


def _preferred_language_codes() -> List[str]:
    raw = str(getattr(config, "YANDEX_OCR_LANGUAGE_CODES", "ru,en") or "ru,en")
    codes = [x.strip() for x in raw.split(",") if x.strip()]
    return codes or list(YANDEX_VISION_LANGUAGE_CODES)


def yandex_ocr_quota_or_temporary_message(exc: Exception) -> str:
    if isinstance(exc, YandexOCRQuotaError):
        return (
            "OCR временно недоступен из-за лимитов Yandex (rate limit). "
            "Повторите загрузку через 30-60 секунд."
        )
    if isinstance(exc, YandexOCRTemporaryError):
        return (
            "OCR временно недоступен из-за проблем на стороне Yandex. "
            "Повторите попытку через 1-2 минуты."
        )
    return str(exc)


def yandex_ocr_is_temporary(exc: Exception) -> bool:
    return isinstance(exc, (YandexOCRQuotaError, YandexOCRTemporaryError))


def _text_from_new_ocr_annotation(ta: Dict[str, Any]) -> str:
    """Extract text from new OCR API textAnnotation using fullText or blocks fallback."""
    full_text = ta.get("fullText")
    if full_text:
        return full_text.strip()
    lines = []
    for block in (ta.get("blocks") or []):
        for line in (block.get("lines") or []):
            text = line.get("text") or ""
            if text:
                lines.append(text)
    return "\n".join(lines).strip()


def _new_ocr_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Api-Key {config.YANDEX_API_KEY}",
        "x-folder-id": config.YANDEX_FOLDER_ID,
        "Content-Type": "application/json",
    }


def _call_new_ocr_async(
    b64_content: str,
    *,
    model: str = "page",
    timeout_sec: int = 600,
    language_codes: Sequence[str] = ("*",),
) -> List[Tuple[int, str]]:
    """
    New Yandex OCR API (async) for multi-page PDFs.
    Sends recognizeTextAsync, polls getRecognition until done.
    Returns list of (page_index_0based, text) sorted by page.
    """
    if not vision_api_configured():
        raise ValueError("Yandex Vision: не заданы YANDEX_API_KEY или YANDEX_FOLDER_ID.")

    headers = _new_ocr_headers()
    body = {
        "mimeType": "application/pdf",
        "languageCodes": list(language_codes),
        "model": model,
        "content": b64_content,
    }

    # Start async operation
    _wait_rate_limit()
    resp = requests.post(
        VISION_OCR_RECOGNIZE_TEXT_ASYNC_URL,
        json=body,
        headers=headers,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"recognizeTextAsync вернул {resp.status_code}: {resp.text[:400]}"
        )
    op_data = resp.json()
    op_id = op_data.get("id")
    if not op_id:
        raise RuntimeError(
            f"recognizeTextAsync: нет operation ID в ответе: {resp.text[:200]}"
        )
    logger.info("Yandex OCR async operation started: id=%s model=%s", op_id, model)

    # Poll for results
    poll_interval = 3.0
    waited = 0.0
    while waited < timeout_sec:
        time.sleep(poll_interval)
        waited += poll_interval
        try:
            r = requests.get(
                VISION_OCR_GET_RECOGNITION_URL,
                params={"operationId": op_id},
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.warning("getRecognition poll error: %s", exc)
            continue

        if r.status_code != 200:
            logger.warning("getRecognition %s → %s", op_id, r.status_code)
            continue

        raw = r.text.strip()
        if not raw:
            continue

        pages: List[Tuple[int, str]] = []

        # Response may be JSON Lines (one per page) or a single JSON object
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            # Check for pending operation (not done yet)
            if item.get("done") is False:
                pages = []
                break

            # Unwrap: could be {result:{textAnnotation,page}} or {textAnnotation,page}
            result = item.get("result") or item
            ta = result.get("textAnnotation") or {}
            text = _text_from_new_ocr_annotation(ta)
            page_num = int(result.get("page", "0") or "0")
            if text:
                pages.append((page_num, text))

        if pages:
            pages.sort(key=lambda x: x[0])
            logger.info(
                "Yandex OCR async done: op=%s model=%s pages=%s waited=%.1fs",
                op_id,
                model,
                len(pages),
                waited,
            )
            return pages

    raise YandexOCRTemporaryError(
        f"recognizeTextAsync timed out after {timeout_sec}s for op={op_id}"
    )


def yandex_vision_recognize_text(
    image_bytes: bytes,
    *,
    filename: str = "",
    timeout_sec: int = 120,
) -> str:
    """Single image -> recognized text."""
    payload = normalize_image_for_yandex(image_bytes, filename=filename)
    if len(payload) > YANDEX_VISION_IMAGE_BYTES_SOFT_LIMIT:
        raise ValueError(
            f"Изображение '{filename or 'unknown'}' слишком большое для OCR после нормализации "
            f"({len(payload)} bytes). Сожмите изображение до ~10 МБ и повторите."
        )
    b64 = base64.b64encode(payload).decode("ascii")
    data = _call_batch_analyze_base64(
        b64,
        timeout_sec=timeout_sec,
        language_codes=_preferred_language_codes(),
    )
    text = extract_text_from_vision_response(data)
    if not text:
        logger.warning("Yandex Vision OCR: empty text result.")
        return ""
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
            data = _call_batch_analyze_base64(
                b64,
                timeout_sec=timeout,
                language_codes=_preferred_language_codes(),
            )
            pairs = documents_from_vision_response(data, page_offset=p0, filename=filename)
            # Vision может вернуть меньше страниц, чем в чанке — заполняем пропуски пустыми не будем
            all_pages.extend(pairs)

        all_pages.sort(key=lambda x: x[0])
        return all_pages
    finally:
        src.close()


def yandex_vision_ocr_pdf_to_page_documents_new_api(
    content: bytes,
    filename: str,
    *,
    model: str = "page",
) -> List[Tuple[int, str]]:
    """
    PDF → список (индекс_страницы_0_based, текст) через новый OCR API (async).
    Поддерживает model='table' для PDF из Excel-таблиц.
    Разбивает на чанки по 9 МБ / 200 страниц, как и старый метод.
    """
    try:
        import fitz  # pymupdf
    except ImportError as e:
        raise RuntimeError(
            "Для OCR больших PDF нужен пакет pymupdf. Установите: pip install pymupdf"
        ) from e

    if not vision_api_configured():
        raise ValueError("Yandex Vision: не заданы API ключ или каталог.")

    max_pages = max(1, int(getattr(config, "YANDEX_VISION_MAX_PDF_PAGES", 200) or 200))
    timeout_per_chunk = max(120, int(getattr(config, "YANDEX_OCR_ASYNC_TIMEOUT_SEC", 300) or 300))
    lang_codes = _preferred_language_codes()
    # New API: ["*"] for auto-detect, which covers mixed documents better
    ocr_langs = ["*"] if set(lang_codes) == {"ru", "en"} else lang_codes

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
            chunk_bytes = build_subpdf_bytes(p0, p1)
            logger.info(
                "Yandex OCR (new API, model=%s) chunk %s/%s: pages %s–%s (%s bytes), file=%s",
                model,
                ri + 1,
                len(ranges),
                p0 + 1,
                p1,
                len(chunk_bytes),
                filename,
            )
            b64 = base64.b64encode(chunk_bytes).decode("ascii")
            pairs = _call_new_ocr_async(
                b64,
                model=model,
                timeout_sec=timeout_per_chunk,
                language_codes=ocr_langs,
            )
            # Shift page indices by chunk offset
            all_pages.extend((p0 + local_idx, text) for local_idx, text in pairs)

        all_pages.sort(key=lambda x: x[0])
        return all_pages
    finally:
        src.close()


def yandex_vision_ocr_pdf_documents_for_langchain(
    content: bytes,
    filename: str,
    *,
    model: str | None = None,
):
    """
    Обёртка под langchain_core.documents.Document.
    model=None → старый batchAnalyze API (обратная совместимость).
    model='table'/'page'/etc → новый OCR API с выбором модели.
    """
    from langchain_core.documents import Document

    if model is not None:
        pairs = yandex_vision_ocr_pdf_to_page_documents_new_api(content, filename, model=model)
        ocr_engine = f"yandex_vision_new_api_{model}"
    else:
        pairs = yandex_vision_ocr_pdf_to_page_documents(content, filename)
        ocr_engine = "yandex_vision_pdf"

    return [
        Document(
            page_content=text,
            metadata={
                "source_file": filename,
                "source_page": idx,
                "ocr": True,
                "ocr_engine": ocr_engine,
            },
        )
        for idx, text in pairs
    ]
