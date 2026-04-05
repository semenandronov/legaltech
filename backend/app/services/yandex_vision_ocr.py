"""Yandex Cloud Vision OCR — распознавание текста с изображений (фото, скрины, сканы)."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional

import requests

from app.config import config

logger = logging.getLogger(__name__)

VISION_BATCH_ANALYZE_URL = "https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze"


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


def extract_text_from_vision_response(data: Dict[str, Any]) -> str:
    """
    Разбор ответа batchAnalyze: results[].results[].textDetection.pages...
    """
    lines: List[str] = []
    for spec in data.get("results") or []:
        for inner in spec.get("results") or []:
            td = inner.get("textDetection") or inner.get("text_detection")
            if not td:
                continue
            lines.extend(_extract_lines_from_text_detection(td))
    return "\n".join(lines).strip()


def yandex_vision_recognize_text(
    image_bytes: bytes,
    *,
    timeout_sec: int = 120,
) -> str:
    """
    Отправляет изображение в Yandex Vision OCR, возвращает распознанный текст.

    Требуются YANDEX_API_KEY и YANDEX_FOLDER_ID и роль ai.vision.user на каталог.
    """
    if not config.YANDEX_API_KEY:
        raise ValueError(
            "YANDEX_API_KEY не задан — распознавание изображений через Yandex Vision недоступно."
        )
    if not config.YANDEX_FOLDER_ID:
        raise ValueError(
            "YANDEX_FOLDER_ID не задан — Yandex Vision требует идентификатор каталога."
        )

    b64 = base64.b64encode(image_bytes).decode("ascii")
    body: Dict[str, Any] = {
        "folderId": config.YANDEX_FOLDER_ID,
        "analyze_specs": [
            {
                "content": b64,
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
        data = resp.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Yandex Vision: невалидный JSON: {e}") from e

    text = extract_text_from_vision_response(data)
    if not text:
        logger.warning("Yandex Vision OCR: пустой текст (возможно, нет текста на изображении).")
    return text
