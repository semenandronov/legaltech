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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Sequence, Tuple

import requests

from app.config import config
from app.services.yandex_privacy import apply_data_logging_headers

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
_last_start_monotonic = 0.0
_last_poll_monotonic = 0.0
_last_legacy_monotonic = 0.0


@dataclass(frozen=True)
class _PdfOcrChunkSpec:
    """One PDF sub-document sent to recognizeTextAsync (typically a single page)."""

    chunk_index: int
    p0: int
    p1: int
    b64: str


class YandexOCRTemporaryError(RuntimeError):
    """Temporary upstream issue (rate limit, transient server/network)."""


class YandexOCRQuotaError(YandexOCRTemporaryError):
    """Rate-limit / quota exceeded."""


class YandexOcrOperationFailedError(RuntimeError):
    """Yandex accepted async OCR but the operation finished with a non-OK status."""


def vision_api_configured() -> bool:
    return bool(config.YANDEX_API_KEY and config.YANDEX_FOLDER_ID)


def _pace_ocr_api(kind: Literal["start", "poll", "legacy"] = "legacy") -> None:
    """Separate pacing for async start (10/s quota) vs poll (50/s) vs legacy batch API."""
    global _last_start_monotonic, _last_poll_monotonic, _last_legacy_monotonic
    if kind == "start":
        min_interval = float(
            getattr(config, "YANDEX_OCR_MIN_START_INTERVAL_SEC", 0.12) or 0.12
        )
    elif kind == "poll":
        min_interval = float(
            getattr(config, "YANDEX_OCR_MIN_POLL_INTERVAL_SEC", 0.0) or 0.0
        )
    else:
        min_interval = float(
            getattr(
                config,
                "YANDEX_OCR_MIN_REQUEST_INTERVAL_SEC",
                YANDEX_VISION_MIN_REQUEST_INTERVAL_SEC,
            )
        )
    if min_interval <= 0:
        return
    with _request_gate_lock:
        now = time.monotonic()
        if kind == "start":
            last = _last_start_monotonic
        elif kind == "poll":
            last = _last_poll_monotonic
        else:
            last = _last_legacy_monotonic
        wait_for = min_interval - (now - last)
        if wait_for > 0:
            time.sleep(wait_for)
        updated = time.monotonic()
        if kind == "start":
            _last_start_monotonic = updated
        elif kind == "poll":
            _last_poll_monotonic = updated
        else:
            _last_legacy_monotonic = updated


def _wait_rate_limit() -> None:
    """Backward-compatible alias for batchAnalyze / single-threaded paths."""
    _pace_ocr_api("legacy")


def _async_parallel_enabled(num_chunks: int) -> bool:
    if num_chunks <= 1:
        return False
    return bool(getattr(config, "YANDEX_OCR_ASYNC_PARALLEL_ENABLED", True))


def _async_max_parallel_workers(num_chunks: int) -> int:
    cap = max(1, int(getattr(config, "YANDEX_OCR_ASYNC_MAX_PARALLEL_CHUNKS", 5) or 5))
    return max(1, min(cap, num_chunks, 10))


def _start_chunk_ocr(
    chunk: _PdfOcrChunkSpec,
    *,
    model: str,
    language_codes: Sequence[str],
) -> _StartedOcrOp:
    op_id = _recognize_text_async_start(
        chunk.b64,
        model=model,
        language_codes=language_codes,
    )
    logger.info(
        "Yandex OCR async started: op=%s model=%s chunk=%s pages %s–%s",
        op_id,
        model,
        chunk.chunk_index + 1,
        chunk.p0 + 1,
        chunk.p1,
    )
    return _StartedOcrOp(chunk=chunk, op_id=op_id, model=model)


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
    headers = apply_data_logging_headers(
        {
            "Authorization": f"Api-Key {config.YANDEX_API_KEY}",
            "Content-Type": "application/json",
            "x-client-request-id": str(uuid.uuid4()),
        }
    )
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


def yandex_ocr_operation_failed_message(exc: Exception) -> str:
    if isinstance(exc, YandexOcrOperationFailedError):
        return (
            "Yandex OCR отклонил распознавание PDF (операция завершилась с ошибкой на стороне сервиса). "
            f"Детали: {exc}"
        )
    return str(exc)


def _ocr_http_timeout_pair(read_sec: float) -> Tuple[float, float]:
    """(connect, read) for requests — отдельный connect, длинный read на тяжёлый OCR."""
    read_val = max(30.0, float(read_sec))
    connect_val = min(30.0, max(5.0, read_val * 0.15))
    return (connect_val, read_val)


def _ocr_http_start_timeout() -> Tuple[float, float]:
    raw = float(getattr(config, "YANDEX_OCR_HTTP_START_TIMEOUT_SEC", 180) or 180)
    return _ocr_http_timeout_pair(raw)


def _ocr_http_poll_timeout() -> Tuple[float, float]:
    raw = float(getattr(config, "YANDEX_OCR_HTTP_POLL_TIMEOUT_SEC", 120) or 120)
    return _ocr_http_timeout_pair(raw)


def _new_ocr_headers() -> Dict[str, str]:
    # Api-Key: не передаём x-folder-id (каталог SA подставляется сервисом). См. Vision OCR docs.
    return apply_data_logging_headers(
        {
            "Authorization": f"Api-Key {config.YANDEX_API_KEY}",
            "Content-Type": "application/json",
            "x-client-request-id": str(uuid.uuid4()),
        }
    )


def _yandex_api_error_fields(payload: Any) -> Dict[str, Any]:
    """Извлечь code/message/details из JSON-ошибки Yandex OCR / Operation API."""
    if not isinstance(payload, dict):
        return {}
    err = payload.get("error")
    if not isinstance(err, dict):
        return {}
    details = err.get("details")
    return {
        "code": err.get("code"),
        "message": err.get("message"),
        "details": details if details else None,
    }


def _log_yandex_ocr_api_error(
    context: str,
    *,
    op_id: str | None = None,
    model: str | None = None,
    status_code: int | None = None,
    payload: Any = None,
    raw_text: str | None = None,
) -> None:
    """Полный JSON ошибки Yandex — для диагностики non-OK и мгновенных сбоев операции."""
    fields = _yandex_api_error_fields(payload) if payload is not None else {}
    parts = [context]
    if op_id:
        parts.append(f"op_id={op_id}")
    if model:
        parts.append(f"model={model}")
    if status_code is not None:
        parts.append(f"http_status={status_code}")
    if fields:
        code = fields.get("code")
        msg = fields.get("message")
        if code is not None:
            parts.append(f"code={code}")
        if msg:
            parts.append(f"message={msg}")
        details = fields.get("details")
        if details:
            try:
                details_s = json.dumps(details, ensure_ascii=False)
            except (TypeError, ValueError):
                details_s = str(details)
            parts.append(f"details={details_s}")
    logger.error("Yandex OCR API error: %s", " ".join(parts))
    # Do not log full OCR error payloads/bodies — they may include recognition text.


def _raise_if_operation_start_failed(op_data: Dict[str, Any], *, model: str) -> None:
    """recognizeTextAsync may return done=true + error without waiting for getRecognition."""
    if not isinstance(op_data, dict):
        return
    err = op_data.get("error")
    if not err and op_data.get("done") is True:
        err = op_data.get("error")
    if err and isinstance(err, dict):
        op_id = str(op_data.get("id") or "")
        _log_yandex_ocr_api_error(
            "recognizeTextAsync immediate failure",
            op_id=op_id or None,
            model=model,
            payload=op_data,
        )
        msg = err.get("message") or str(err)
        code = err.get("code")
        raise YandexOcrOperationFailedError(
            f"recognizeTextAsync model={model} failed immediately: code={code} message={msg}"
        )


def _async_max_pages_per_request() -> int:
    return max(
        1,
        int(
            getattr(config, "YANDEX_OCR_ASYNC_MAX_PAGES_PER_REQUEST", 1) or 1
        ),
    )


def _handle_get_recognition_non_ok(
    response: requests.Response,
    op_id: str,
    *,
    model: str | None = None,
) -> None:
    """Fail fast on terminal 400; log other non-200 for debugging."""
    _raise_if_get_recognition_fatal(response, op_id, model=model)
    if response.status_code == 400:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        _log_yandex_ocr_api_error(
            "getRecognition non-fatal 400",
            op_id=op_id,
            model=model,
            status_code=400,
            payload=payload,
            raw_text=None if payload is not None else (response.text or ""),
        )


def _raise_if_get_recognition_fatal(
    response: requests.Response,
    op_id: str,
    *,
    model: str | None = None,
) -> None:
    """getRecognition 400 with non-OK means the async job failed — polling will never succeed."""
    if response.status_code != 400:
        return
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    err = payload.get("error") if isinstance(payload, dict) else {}
    msg = ""
    if isinstance(err, dict):
        msg = str(err.get("message") or "")
    if "non-OK" in msg or "non-ok" in msg.lower():
        _log_yandex_ocr_api_error(
            "getRecognition operation finished non-OK",
            op_id=op_id,
            model=model,
            status_code=400,
            payload=payload if isinstance(payload, dict) else None,
            raw_text=response.text if not isinstance(payload, dict) else None,
        )
        raise YandexOcrOperationFailedError(
            f"Yandex OCR operation {op_id} failed: {msg or response.text[:500]}"
        )


def _recognize_text_async_start(
    b64_content: str,
    *,
    model: str,
    language_codes: Sequence[str],
) -> str:
    """POST recognizeTextAsync; returns operation id."""
    headers = _new_ocr_headers()
    body = {
        "mimeType": "application/pdf",
        "languageCodes": list(language_codes),
        "model": model,
        "content": b64_content,
    }
    _pace_ocr_api("start")
    resp = requests.post(
        VISION_OCR_RECOGNIZE_TEXT_ASYNC_URL,
        json=body,
        headers=headers,
        timeout=_ocr_http_start_timeout(),
    )
    if resp.status_code == 429:
        raise YandexOCRQuotaError(
            f"recognizeTextAsync rate limited (429): {resp.text[:300]}"
        )
    if resp.status_code != 200:
        try:
            err_payload = resp.json()
        except ValueError:
            err_payload = None
        _log_yandex_ocr_api_error(
            "recognizeTextAsync HTTP error",
            model=model,
            status_code=resp.status_code,
            payload=err_payload,
            raw_text=None if err_payload is not None else (resp.text or ""),
        )
        raise RuntimeError(
            f"recognizeTextAsync вернул {resp.status_code}: {resp.text[:400]}"
        )
    op_data = resp.json()
    _raise_if_operation_start_failed(op_data, model=model)
    op_id = op_data.get("id")
    if not op_id:
        raise RuntimeError(
            f"recognizeTextAsync: нет operation ID в ответе: {resp.text[:200]}"
        )
    return str(op_id)


def _shared_initial_poll_delay_sec() -> float:
    return float(
        getattr(config, "YANDEX_OCR_ASYNC_INITIAL_POLL_DELAY_SEC", 2.0) or 2.0
    )


def _parse_plain_recognition_lines(
    raw: str,
) -> Tuple[bool, bool, List[Tuple[int, str]]]:
    """Returns (found_pending, found_done, page_results)."""
    found_pending = False
    found_done = False
    page_results: List[Tuple[int, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("done") is False:
            found_pending = True
            break
        if item.get("done") is True:
            inner = item.get("response") or item.get("result") or {}
            ta = inner.get("textAnnotation") or {}
            text = _text_from_new_ocr_annotation(ta)
            page_num = int((inner.get("page") or "0"))
            page_results.append((page_num, text))
            found_done = True
            continue
        inner = item.get("result") or item.get("response") or item
        ta = inner.get("textAnnotation") or {}
        text = _text_from_new_ocr_annotation(ta)
        page_num = int((inner.get("page") or "0"))
        page_results.append((page_num, text))
        found_done = True
    return found_pending, found_done, page_results


def _parse_structured_recognition_lines(
    raw: str,
    *,
    page_offset: int,
) -> Tuple[bool, bool, List["YandexOcrPage"]]:
    from app.services.yandex_ocr_structured import YandexOcrPage, parse_text_annotation

    found_pending = False
    found_done = False
    page_results: List[YandexOcrPage] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("done") is False:
            found_pending = True
            break
        inner = item.get("response") or item.get("result") or item
        if item.get("done") is True and not inner.get("textAnnotation"):
            inner = item.get("response") or item.get("result") or {}
        ta = inner.get("textAnnotation") or {}
        local_page = int(inner.get("page") if inner.get("page") is not None else 0)
        global_idx = page_offset + local_page
        parsed = parse_text_annotation(
            ta,
            page_index=global_idx,
            page_no_1based=global_idx + 1,
        )
        if parsed.page_text.strip():
            page_results.append(parsed)
        found_done = True
    return found_pending, found_done, page_results


def _poll_plain_recognition(
    op_id: str,
    *,
    model: str,
    timeout_sec: int,
    skip_initial_delay: bool = False,
) -> List[Tuple[int, str]]:
    headers = _new_ocr_headers()
    poll_interval = 3.0
    waited = 0.0
    not_found_streak = 0
    initial_delay = 0.0 if skip_initial_delay else _shared_initial_poll_delay_sec()
    if initial_delay > 0:
        time.sleep(min(20.0, initial_delay))
        waited += min(20.0, initial_delay)
    while waited < timeout_sec:
        time.sleep(poll_interval)
        waited += poll_interval
        _pace_ocr_api("poll")
        try:
            r = requests.get(
                VISION_OCR_GET_RECOGNITION_URL,
                params={"operationId": op_id},
                headers=headers,
                timeout=_ocr_http_poll_timeout(),
            )
        except requests.RequestException as exc:
            logger.warning("getRecognition poll error: %s", exc)
            continue
        if r.status_code == 429:
            raise YandexOCRQuotaError(f"getRecognition rate limited (429) op={op_id}")
        if r.status_code != 200:
            if r.status_code == 404:
                not_found_streak += 1
                poll_interval = min(10.0, poll_interval * 1.5)
                continue
            _handle_get_recognition_non_ok(r, op_id, model=model)
            logger.warning(
                "getRecognition %s → %s body=%s",
                op_id,
                r.status_code,
                (r.text or "")[:300],
            )
            continue
        not_found_streak = 0
        raw = r.text.strip()
        if not raw:
            continue
        found_pending, found_done, page_results = _parse_plain_recognition_lines(raw)
        if found_pending or not found_done:
            if waited >= 30:
                poll_interval = min(10.0, poll_interval * 1.2)
            continue
        pages = [(n, t) for n, t in page_results if t.strip()]
        pages.sort(key=lambda x: x[0])
        logger.info(
            "Yandex OCR async done: op=%s model=%s pages_with_text=%s/%s waited=%.1fs",
            op_id,
            model,
            len(pages),
            len(page_results),
            waited,
        )
        return pages
    raise YandexOCRTemporaryError(
        f"recognizeTextAsync timed out after {timeout_sec}s for op={op_id}"
    )


def _poll_structured_recognition(
    op_id: str,
    *,
    model: str,
    page_offset: int,
    timeout_sec: int,
    skip_initial_delay: bool = False,
) -> List["YandexOcrPage"]:
    headers = _new_ocr_headers()
    poll_interval = 3.0
    waited = 0.0
    not_found_streak = 0
    initial_delay = 0.0 if skip_initial_delay else _shared_initial_poll_delay_sec()
    if initial_delay > 0:
        time.sleep(min(20.0, initial_delay))
        waited += min(20.0, initial_delay)
    while waited < timeout_sec:
        time.sleep(poll_interval)
        waited += poll_interval
        _pace_ocr_api("poll")
        try:
            r = requests.get(
                VISION_OCR_GET_RECOGNITION_URL,
                params={"operationId": op_id},
                headers=headers,
                timeout=_ocr_http_poll_timeout(),
            )
        except requests.RequestException as exc:
            logger.warning("getRecognition poll error: %s", exc)
            continue
        if r.status_code == 429:
            raise YandexOCRQuotaError(f"getRecognition rate limited (429) op={op_id}")
        if r.status_code != 200:
            if r.status_code == 404:
                not_found_streak += 1
                poll_interval = min(10.0, poll_interval * 1.5)
                continue
            _handle_get_recognition_non_ok(r, op_id, model=model)
            logger.warning(
                "getRecognition %s → %s body=%s",
                op_id,
                r.status_code,
                (r.text or "")[:300],
            )
            continue
        not_found_streak = 0
        raw = r.text.strip()
        if not raw:
            continue
        found_pending, found_done, page_results = _parse_structured_recognition_lines(
            raw, page_offset=page_offset
        )
        if found_pending or not found_done:
            if waited >= 30:
                poll_interval = min(10.0, poll_interval * 1.2)
            continue
        page_results.sort(key=lambda p: p.page_index)
        logger.info(
            "Yandex OCR structured done: op=%s model=%s pages=%s waited=%.1fs",
            op_id,
            model,
            len(page_results),
            waited,
        )
        return page_results
    raise YandexOCRTemporaryError(
        f"recognizeTextAsync timed out after {timeout_sec}s for op={op_id}"
    )


@dataclass
class _StartedOcrOp:
    chunk: _PdfOcrChunkSpec
    op_id: str
    model: str


def _run_pdf_chunks_structured_parallel(
    chunks: List[_PdfOcrChunkSpec],
    *,
    ocr_model: str,
    timeout_sec: int,
    language_codes: Sequence[str],
    filename: str,
) -> List["YandexOcrPage"]:
    workers = _async_max_parallel_workers(len(chunks))
    logger.info(
        "Yandex OCR structured parallel: %s chunks, workers=%s, model=%s file=%s",
        len(chunks),
        workers,
        ocr_model,
        filename,
    )
    started: List[_StartedOcrOp] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yandex-ocr-start") as pool:
        futures = {
            pool.submit(
                _start_chunk_ocr,
                chunk,
                model=ocr_model,
                language_codes=language_codes,
            ): chunk
            for chunk in chunks
        }
        for fut in as_completed(futures):
            started.append(fut.result())

    initial_delay = _shared_initial_poll_delay_sec()
    if initial_delay > 0:
        time.sleep(min(20.0, initial_delay))

    all_pages: List["YandexOcrPage"] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yandex-ocr-poll") as pool:
        futures = {
            pool.submit(
                _poll_structured_recognition,
                op.op_id,
                model=op.model,
                page_offset=op.chunk.p0,
                timeout_sec=timeout_sec,
                skip_initial_delay=True,
            ): op
            for op in started
        }
        for fut in as_completed(futures):
            all_pages.extend(fut.result())
    all_pages.sort(key=lambda p: p.page_index)
    return all_pages


def _run_pdf_chunks_plain_parallel(
    chunks: List[_PdfOcrChunkSpec],
    *,
    model: str,
    timeout_sec: int,
    language_codes: Sequence[str],
    filename: str,
) -> List[Tuple[int, str]]:
    workers = _async_max_parallel_workers(len(chunks))
    logger.info(
        "Yandex OCR plain parallel: %s chunks, workers=%s, model=%s file=%s",
        len(chunks),
        workers,
        model,
        filename,
    )
    started: List[_StartedOcrOp] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yandex-ocr-start") as pool:
        futures = {
            pool.submit(
                _start_chunk_ocr,
                chunk,
                model=model,
                language_codes=language_codes,
            ): chunk
            for chunk in chunks
        }
        for fut in as_completed(futures):
            started.append(fut.result())

    initial_delay = _shared_initial_poll_delay_sec()
    if initial_delay > 0:
        time.sleep(min(20.0, initial_delay))

    all_pages: List[Tuple[int, str]] = []
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yandex-ocr-poll") as pool:
        future_to_op = {
            pool.submit(
                _poll_plain_recognition,
                op.op_id,
                model=op.model,
                timeout_sec=timeout_sec,
                skip_initial_delay=True,
            ): op
            for op in started
        }
        for fut in as_completed(future_to_op):
            pairs = fut.result()
            op = future_to_op[fut]
            all_pages.extend((op.chunk.p0 + local_idx, text) for local_idx, text in pairs)
    all_pages.sort(key=lambda x: x[0])
    return all_pages


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


def _call_new_ocr_async(
    b64_content: str,
    *,
    model: str = "page",
    timeout_sec: int = 600,
    language_codes: Sequence[str] = ("*",),
) -> List[Tuple[int, str]]:
    """Single PDF chunk: recognizeTextAsync + poll until done."""
    if not vision_api_configured():
        raise ValueError("Yandex Vision: не заданы YANDEX_API_KEY или YANDEX_FOLDER_ID.")
    op_id = _recognize_text_async_start(
        b64_content, model=model, language_codes=language_codes
    )
    logger.info("Yandex OCR async operation started: id=%s model=%s", op_id, model)
    return _poll_plain_recognition(op_id, model=model, timeout_sec=timeout_sec)


def _call_new_ocr_async_structured_once(
    b64_content: str,
    *,
    model: str = "page",
    timeout_sec: int = 600,
    language_codes: Sequence[str] = ("*",),
    page_offset: int = 0,
) -> List["YandexOcrPage"]:
    """Single PDF chunk: structured OCR via model=page."""
    if not vision_api_configured():
        raise ValueError("Yandex Vision: не заданы YANDEX_API_KEY или YANDEX_FOLDER_ID.")
    op_id = _recognize_text_async_start(
        b64_content, model=model, language_codes=language_codes
    )
    logger.info("Yandex OCR async (structured) started: id=%s model=%s", op_id, model)
    return _poll_structured_recognition(
        op_id,
        model=model,
        page_offset=page_offset,
        timeout_sec=timeout_sec,
    )


def _call_new_ocr_async_structured(
    b64_content: str,
    *,
    model: str = "page",
    timeout_sec: int = 600,
    language_codes: Sequence[str] = ("*",),
    page_offset: int = 0,
) -> List["YandexOcrPage"]:
    """Single PDF chunk: structured OCR (model=page)."""
    return _call_new_ocr_async_structured_once(
        b64_content,
        model=model,
        timeout_sec=timeout_sec,
        language_codes=language_codes,
        page_offset=page_offset,
    )


def yandex_vision_ocr_pdf_structured(
    content: bytes,
    filename: str,
    *,
    model: str | None = None,
) -> List["YandexOcrPage"]:
    """PDF → structured pages (blocks, bbox) via new OCR API, model=page only."""
    from app.services.yandex_ocr_structured import YandexOcrPage

    try:
        import fitz  # pymupdf
    except ImportError as e:
        raise RuntimeError(
            "Для OCR больших PDF нужен пакет pymupdf. Установите: pip install pymupdf"
        ) from e

    if not vision_api_configured():
        raise ValueError("Yandex Vision: не заданы API ключ или каталог.")

    if model is not None and str(model).lower() != "page":
        logger.warning("Yandex OCR PDF: model=%s ignored, using page only", model)
    ocr_model = "page"
    max_pages = _async_max_pages_per_request()
    timeout_per_chunk = max(120, int(getattr(config, "YANDEX_OCR_ASYNC_TIMEOUT_SEC", 300) or 300))
    lang_codes = _preferred_language_codes()
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

        NEW_API_BYTES_SOFT_LIMIT = 9 * 1024 * 1024
        ranges = _pdf_chunk_page_ranges(
            total,
            max_pages,
            lambda s, e: build_subpdf_bytes(s, e),
            bytes_soft_limit=NEW_API_BYTES_SOFT_LIMIT,
        )

        chunk_specs: List[_PdfOcrChunkSpec] = []
        for ri, (p0, p1) in enumerate(ranges):
            chunk_bytes = build_subpdf_bytes(p0, p1)
            logger.info(
                "Yandex OCR structured chunk %s/%s: pages %s–%s model=%s file=%s",
                ri + 1,
                len(ranges),
                p0 + 1,
                p1,
                ocr_model,
                filename,
            )
            chunk_specs.append(
                _PdfOcrChunkSpec(
                    chunk_index=ri,
                    p0=p0,
                    p1=p1,
                    b64=base64.b64encode(chunk_bytes).decode("ascii"),
                )
            )

        if len(chunk_specs) == 1:
            spec = chunk_specs[0]
            logger.info(
                "Yandex OCR structured single request: pages 1–%s model=%s file=%s (%s bytes)",
                total,
                ocr_model,
                filename,
                len(build_subpdf_bytes(spec.p0, spec.p1)),
            )
            return _call_new_ocr_async_structured(
                spec.b64,
                model=ocr_model,
                timeout_sec=timeout_per_chunk,
                language_codes=ocr_langs,
                page_offset=spec.p0,
            )

        if _async_parallel_enabled(len(chunk_specs)):
            all_pages = _run_pdf_chunks_structured_parallel(
                chunk_specs,
                ocr_model=ocr_model,
                timeout_sec=timeout_per_chunk,
                language_codes=ocr_langs,
                filename=filename,
            )
        else:
            all_pages = []
            for spec in chunk_specs:
                chunk_pages = _call_new_ocr_async_structured(
                    spec.b64,
                    model=ocr_model,
                    timeout_sec=timeout_per_chunk,
                    language_codes=ocr_langs,
                    page_offset=spec.p0,
                )
                all_pages.extend(chunk_pages)
            all_pages.sort(key=lambda p: p.page_index)
        return all_pages
    finally:
        src.close()


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
    bytes_soft_limit: int = 0,
) -> List[Tuple[int, int]]:
    """
    Диапазоны [start, end) в страницах 0-based, чтобы каждый под-PDF не превышал max_pages
    и bytes_soft_limit байт (по умолчанию — YANDEX_VISION_PDF_BYTES_SOFT_LIMIT).
    pdf_bytes_factory(start, end) -> bytes для проверки размера.
    """
    if total_pages <= 0 or max_pages <= 0:
        return []
    limit = bytes_soft_limit if bytes_soft_limit > 0 else YANDEX_VISION_PDF_BYTES_SOFT_LIMIT
    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < total_pages:
        end = min(start + max_pages, total_pages)
        # Уменьшаем end пока размер > soft limit (минимум 1 страница)
        while end > start + 1:
            chunk = pdf_bytes_factory(start, end)
            if len(chunk) <= limit:
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

    max_pages = _async_max_pages_per_request()
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

        # New OCR API uses HTTP (not gRPC), so 10 MB limit applies — use 9 MB soft limit
        NEW_API_BYTES_SOFT_LIMIT = 9 * 1024 * 1024
        ranges = _pdf_chunk_page_ranges(
            total,
            max_pages,
            lambda s, e: build_subpdf_bytes(s, e),
            bytes_soft_limit=NEW_API_BYTES_SOFT_LIMIT,
        )

        chunk_specs: List[_PdfOcrChunkSpec] = []
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
            chunk_specs.append(
                _PdfOcrChunkSpec(
                    chunk_index=ri,
                    p0=p0,
                    p1=p1,
                    b64=base64.b64encode(chunk_bytes).decode("ascii"),
                )
            )

        if len(chunk_specs) == 1:
            spec = chunk_specs[0]
            logger.info(
                "Yandex OCR plain single request: pages 1–%s model=%s file=%s",
                total,
                model,
                filename,
            )
            pairs = _call_new_ocr_async(
                spec.b64,
                model=model,
                timeout_sec=timeout_per_chunk,
                language_codes=ocr_langs,
            )
            return [(spec.p0 + local_idx, text) for local_idx, text in pairs]

        if _async_parallel_enabled(len(chunk_specs)):
            return _run_pdf_chunks_plain_parallel(
                chunk_specs,
                model=model,
                timeout_sec=timeout_per_chunk,
                language_codes=ocr_langs,
                filename=filename,
            )

        all_pages: List[Tuple[int, str]] = []
        for spec in chunk_specs:
            pairs = _call_new_ocr_async(
                spec.b64,
                model=model,
                timeout_sec=timeout_per_chunk,
                language_codes=ocr_langs,
            )
            all_pages.extend((spec.p0 + local_idx, text) for local_idx, text in pairs)
        all_pages.sort(key=lambda x: x[0])
        return all_pages
    finally:
        src.close()


def yandex_vision_ocr_pdf_documents_for_langchain(
    content: bytes,
    filename: str,
    *,
    model: str | None = None,
    use_structured: bool = True,
):
    """
    Обёртка под langchain_core.documents.Document.
    use_structured=True (default): новый OCR API + blocks/bbox metadata (model=page).
    model=None → page (единственная модель для PDF).
    """
    from langchain_core.documents import Document

    if use_structured:
        if model is not None and str(model).lower() != "page":
            logger.warning("Yandex OCR PDF: model=%s ignored, using page only", model)
        ocr_model = "page"
        pages = yandex_vision_ocr_pdf_structured(content, filename, model=ocr_model)
        ocr_engine = f"yandex_vision_new_api_{ocr_model}"
        docs: List[Document] = []
        for page in pages:
            block_payload = [
                {
                    "text": b.text,
                    "layout_type": b.layout_type,
                    "bbox": b.bbox,
                }
                for b in page.blocks
            ]
            docs.append(
                Document(
                    page_content=page.page_text,
                    metadata={
                        "source_file": filename,
                        "source_page": page.page_index,
                        "ocr": True,
                        "ocr_engine": ocr_engine,
                        "yandex_markdown": page.markdown or page.page_text,
                        "yandex_blocks": block_payload,
                        "yandex_page_bbox": page.page_bbox,
                    },
                )
            )
        return docs

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
