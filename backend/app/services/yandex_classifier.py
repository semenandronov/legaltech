"""Yandex AI Studio Classifier service for document classification"""
import os
import requests
import logging
from typing import Dict, Any, Optional
from app.config import config

logger = logging.getLogger(__name__)


class YandexDocumentClassifier:
    """Service for classifying documents using Yandex AI Studio"""
    
    def __init__(self):
        """Initialize Yandex AI Studio classifier"""
        # Поддерживаем оба варианта: API ключ (приоритет) или IAM токен
        self.api_key = config.YANDEX_API_KEY
        self.iam_token = config.YANDEX_IAM_TOKEN
        self.folder_id = config.YANDEX_FOLDER_ID
        self.classifier_id = config.YANDEX_AI_STUDIO_CLASSIFIER_ID
        
        # Используем API ключ если есть, иначе IAM токен
        self.auth_token = self.api_key or self.iam_token
        self.use_api_key = bool(self.api_key)
        
        if not self.auth_token:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. "
                "Yandex classifier will not work. Please set them in .env file."
            )
    
    def classify(
        self, 
        text: str, 
        classes: Optional[list] = None
    ) -> Dict[str, Any]:
        """
        Классифицирует документ через Yandex AI Studio
        
        Args:
            text: Текст документа для классификации (макс 4000 символов)
            classes: Список классов для классификации (опционально)
        
        Returns:
            Dictionary с результатом:
            {
                "type": "contract",
                "confidence": 0.95,
                "cost_rub": 0.11,
                "all_classes": [{"class": "contract", "confidence": 0.95}, ...]
            }
        """
        if not self.auth_token:
            raise ValueError(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN must be set in .env file"
            )
        
        if not self.classifier_id:
            raise ValueError(
                "YANDEX_AI_STUDIO_CLASSIFIER_ID must be set. "
                "Create a classifier in https://studio.yandex.cloud first."
            )
        
        # Обрезаем текст до 4000 символов (лимит AI Studio)
        text = text[:4000]
        
        # API endpoint для Yandex AI Studio
        url = f"https://llm.api.cloud.yandex.net/foundationModels/v1/classify"
        
        # Используем API ключ или IAM токен
        if self.use_api_key:
            auth_header = f"Api-Key {self.api_key}"
        else:
            auth_header = f"Bearer {self.iam_token}"
        
        headers = {
            "Authorization": auth_header,
            "Content-Type": "application/json"
        }
        
        # Folder ID добавляем только если указан
        if self.folder_id:
            headers["x-folder-id"] = self.folder_id
        
        payload = {
            "model": self.classifier_id,
            "text": text
        }
        
        # Если указаны классы, добавляем их
        if classes:
            payload["classes"] = classes
        
        try:
            logger.info(f"Classifying document with Yandex AI Studio (text length: {len(text)})")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            
            # Парсим результат
            if "result" in result:
                classification_result = result["result"]
                
                # Находим класс с максимальной уверенностью
                best_class = None
                best_confidence = 0.0
                all_classes = []
                
                if isinstance(classification_result, dict):
                    for class_name, confidence in classification_result.items():
                        all_classes.append({
                            "class": class_name,
                            "confidence": float(confidence)
                        })
                        if float(confidence) > best_confidence:
                            best_confidence = float(confidence)
                            best_class = class_name
                elif isinstance(classification_result, list):
                    for item in classification_result:
                        if isinstance(item, dict):
                            class_name = item.get("class", item.get("label", "unknown"))
                            confidence = float(item.get("confidence", item.get("score", 0.0)))
                            all_classes.append({
                                "class": class_name,
                                "confidence": confidence
                            })
                            if confidence > best_confidence:
                                best_confidence = confidence
                                best_class = class_name
                
                return {
                    "type": best_class or "unknown",
                    "confidence": best_confidence,
                    "cost_rub": 0.11,  # Примерная стоимость
                    "all_classes": all_classes
                }
            else:
                logger.warning(f"Unexpected response format from Yandex AI Studio: {result}")
                return {
                    "type": "unknown",
                    "confidence": 0.0,
                    "cost_rub": 0.11,
                    "all_classes": []
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling Yandex AI Studio API: {e}", exc_info=True)
            raise Exception(f"Ошибка при классификации через Yandex AI Studio: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in Yandex classifier: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при классификации: {str(e)}")
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли классификатор"""
        return bool(self.auth_token and self.classifier_id)  # API ключ или IAM токен + classifier_id
