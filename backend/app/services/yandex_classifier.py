"""
Классификация текста через Yandex AI Studio (Foundation Models Text Classification API).

Документация:
- Обзор REST: https://aistudio.yandex.ru/docs/en/ai-studio/text-classification/api-ref/
- Промптовый классификатор (zero/few-shot): https://aistudio.yandex.ru/docs/en/ai-studio/operations/classifier/readymade.html

Эндпоинты (хост ``llm.api.cloud.yandex.net``):
- Дообученная модель: ``POST .../foundationModels/v1/textClassification`` — тело: ``modelUri``, ``text``; классы заданы при обучении.
- Промптовый YandexGPT: ``POST .../foundationModels/v1/fewShotTextClassification`` — ``modelUri`` (например ``cls://<folder>/yandexgpt/latest``), ``task_description``, ``labels``, ``text``, опционально ``samples``.

Аутентификация: IAM — ``Authorization: Bearer <token>``; API-ключ СА — ``Authorization: Api-Key <key>`` (как в других сервисах каталога).

Поле ``classes`` в :meth:`YandexDocumentClassifier.classify` для дообученной модели не используется (метки фиксированы в модели).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from app.config import config
from app.services.yandex_privacy import apply_data_logging_headers

logger = logging.getLogger(__name__)

_FM_BASE = "https://llm.api.cloud.yandex.net/foundationModels/v1"
URL_TEXT_CLASSIFICATION = f"{_FM_BASE}/textClassification"
URL_FEW_SHOT_CLASSIFICATION = f"{_FM_BASE}/fewShotTextClassification"


class YandexDocumentClassifier:
    """Клиент классификации текста Yandex AI Studio (дообученная модель и опционально few-shot)."""

    def __init__(self) -> None:
        self.api_key = config.YANDEX_API_KEY
        self.iam_token = config.YANDEX_IAM_TOKEN
        self.folder_id = (config.YANDEX_FOLDER_ID or "").strip()
        self.classifier_id = (config.YANDEX_AI_STUDIO_CLASSIFIER_ID or "").strip()
        self.model_uri_override = (config.YANDEX_CLASSIFIER_MODEL_URI or "").strip()

        self.auth_token = self.api_key or self.iam_token
        self.use_api_key = bool(self.api_key)

        if not self.auth_token:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set — Yandex classifier will not work."
            )

    def _auth_header(self) -> str:
        if self.use_api_key:
            return f"Api-Key {self.api_key}"
        return f"Bearer {self.iam_token}"

    def _request_headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Authorization": self._auth_header(),
            "Content-Type": "application/json",
        }
        if self.folder_id:
            h["x-folder-id"] = self.folder_id
        return apply_data_logging_headers(h)

    def _resolve_tuned_model_uri(self) -> str:
        if self.model_uri_override:
            return self.model_uri_override
        if not self.classifier_id:
            return ""
        if self.classifier_id.startswith("cls://"):
            return self.classifier_id
        if self.folder_id:
            return f"cls://{self.folder_id}/{self.classifier_id}"
        return ""

    def _parse_predictions(self, result: Dict[str, Any]) -> Dict[str, Any]:
        raw = result.get("predictions")
        if not isinstance(raw, list):
            logger.warning("Unexpected Yandex classification response: %s", result)
            return {
                "type": "unknown",
                "confidence": 0.0,
                "all_classes": [],
                "model_version": result.get("modelVersion") or result.get("model_version"),
            }

        all_classes: List[Dict[str, Any]] = []
        best_class: Optional[str] = None
        best_confidence = 0.0

        for item in raw:
            if not isinstance(item, dict):
                continue
            label = item.get("label") or item.get("class") or "unknown"
            conf = float(item.get("confidence", item.get("score", 0.0)))
            all_classes.append({"class": label, "confidence": conf})
            if conf > best_confidence:
                best_confidence = conf
                best_class = label

        return {
            "type": best_class or "unknown",
            "confidence": best_confidence,
            "all_classes": all_classes,
            "model_version": result.get("modelVersion") or result.get("model_version"),
        }

    def classify(self, text: str, classes: Optional[list] = None) -> Dict[str, Any]:
        """
        Классификация через **дообученную** модель (``textClassification``).

        Args:
            text: Входной текст.
            classes: Игнорируется для дообученной модели (оставлено для совместимости вызовов).

        Returns:
            ``type``, ``confidence``, ``all_classes``, опционально ``model_version``.
        """
        if not self.auth_token:
            raise ValueError("YANDEX_API_KEY or YANDEX_IAM_TOKEN must be set")

        model_uri = self._resolve_tuned_model_uri()
        if not model_uri:
            raise ValueError(
                "Укажите YANDEX_CLASSIFIER_MODEL_URI (полный cls://...) или "
                "YANDEX_AI_STUDIO_CLASSIFIER_ID вместе с YANDEX_FOLDER_ID."
            )

        if classes:
            logger.debug(
                "Yandex tuned classifier: argument classes=... ignored (labels are fixed in the model)."
            )

        text_trim = text[:8000]

        payload = {"modelUri": model_uri, "text": text_trim}

        logger.info(
            "Yandex textClassification: model_uri=%s, text_len=%s",
            model_uri,
            len(text_trim),
        )

        try:
            response = requests.post(
                URL_TEXT_CLASSIFICATION,
                json=payload,
                headers=self._request_headers(),
                timeout=60,
            )
            if not response.ok:
                logger.error(
                    "textClassification HTTP %s: %s",
                    response.status_code,
                    response.text[:2000],
                )
            response.raise_for_status()
            parsed = self._parse_predictions(response.json())
            return {
                "type": parsed["type"],
                "confidence": parsed["confidence"],
                "all_classes": parsed["all_classes"],
                "cost_rub": None,
                "model_version": parsed.get("model_version"),
            }
        except requests.exceptions.RequestException as e:
            logger.error("Yandex textClassification request failed: %s", e, exc_info=True)
            raise Exception(f"Ошибка при классификации через Yandex AI Studio: {e}") from e

    def classify_few_shot(
        self,
        text: str,
        task_description: str,
        labels: List[str],
        samples: Optional[List[Dict[str, str]]] = None,
        *,
        model_uri: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Промптовая классификация (``fewShotTextClassification``): до 20 классов, опционально примеры.

        ``model_uri`` по умолчанию: ``cls://<YANDEX_FOLDER_ID>/yandexgpt/latest`` (нужен folder_id).
        """
        if not self.auth_token:
            raise ValueError("YANDEX_API_KEY or YANDEX_IAM_TOKEN must be set")

        uri = (model_uri or "").strip()
        if not uri:
            if not self.folder_id:
                raise ValueError("Для few-shot укажите model_uri или YANDEX_FOLDER_ID")
            uri = f"cls://{self.folder_id}/yandexgpt/latest"

        if len(labels) > 20:
            raise ValueError("Few-shot API: не более 20 классов (labels)")

        body: Dict[str, Any] = {
            "modelUri": uri,
            "task_description": task_description,
            "labels": labels,
            "text": text[:8000],
        }
        if samples:
            body["samples"] = samples

        logger.info(
            "Yandex fewShotTextClassification: labels=%s, text_len=%s",
            len(labels),
            len(body["text"]),
        )

        try:
            response = requests.post(
                URL_FEW_SHOT_CLASSIFICATION,
                json=body,
                headers=self._request_headers(),
                timeout=60,
            )
            if not response.ok:
                logger.error(
                    "fewShotTextClassification HTTP %s: %s",
                    response.status_code,
                    response.text[:2000],
                )
            response.raise_for_status()
            parsed = self._parse_predictions(response.json())
            return {
                "type": parsed["type"],
                "confidence": parsed["confidence"],
                "all_classes": parsed["all_classes"],
                "cost_rub": None,
                "model_version": parsed.get("model_version"),
            }
        except requests.exceptions.RequestException as e:
            logger.error(
                "Yandex fewShotTextClassification request failed: %s", e, exc_info=True
            )
            raise Exception(f"Ошибка few-shot классификации Yandex: {e}") from e

    def is_available(self) -> bool:
        return bool(self.auth_token and self._resolve_tuned_model_uri())
