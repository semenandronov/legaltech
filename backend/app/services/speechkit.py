"""Yandex SpeechKit service for audio transcription"""
import os
import requests
import logging
from typing import Dict, Any, Optional
from app.config import config

logger = logging.getLogger(__name__)


class SpeechKitService:
    """Service for speech recognition using Yandex SpeechKit"""
    
    def __init__(self):
        """Initialize SpeechKit service"""
        self.folder_id = config.YANDEX_FOLDER_ID
        self.iam_token = config.YANDEX_IAM_TOKEN
        
        if not self.folder_id or not self.iam_token:
            logger.warning(
                "YANDEX_FOLDER_ID or YANDEX_IAM_TOKEN not set. "
                "SpeechKit will not work. Please set them in .env file."
            )
    
    def transcribe(
        self, 
        audio_file: bytes,
        format: str = "lpcm",
        sample_rate: int = 16000,
        language: str = "ru-RU"
    ) -> Dict[str, Any]:
        """
        Транскрибирует аудио в текст через Yandex SpeechKit
        
        Args:
            audio_file: Байты аудио файла
            format: Формат аудио (lpcm, oggopus, mp3)
            sample_rate: Частота дискретизации (8000, 16000, 48000)
            language: Язык (ru-RU, en-US, etc.)
        
        Returns:
            Dictionary с результатом:
            {
                "text": "Распознанный текст...",
                "confidence": 0.95,
                "duration_seconds": 15.5,
                "cost_rub": 18.6  # ~1.2₽/минута
            }
        """
        if not self.folder_id or not self.iam_token:
            raise ValueError(
                "YANDEX_FOLDER_ID and YANDEX_IAM_TOKEN must be set in .env file"
            )
        
        # API endpoint для SpeechKit
        url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize"
        
        headers = {
            "Authorization": f"Bearer {self.iam_token}",
            "x-folder-id": self.folder_id
        }
        
        # Параметры для распознавания
        params = {
            "lang": language,
            "format": format,
            "sampleRateHertz": sample_rate,
            "model": "general:rc"  # Лучшая модель для юридического русского
        }
        
        try:
            logger.info(f"Transcribing audio (size: {len(audio_file)} bytes, format: {format})")
            
            # SpeechKit принимает аудио как бинарные данные
            response = requests.post(
                url, 
                params=params,
                headers=headers,
                data=audio_file,
                timeout=120  # Долгий таймаут для больших файлов
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Извлекаем текст
            if "result" in result:
                text = result["result"]
                
                # Оцениваем длительность (примерно, на основе размера файла)
                # Для LPCM: размер / (sample_rate * 2 байта на сэмпл * каналы)
                duration_seconds = len(audio_file) / (sample_rate * 2 * 1)  # Предполагаем моно
                cost_rub = duration_seconds / 60 * 1.2  # ~1.2₽/минута
                
                return {
                    "text": text,
                    "confidence": 0.95,  # SpeechKit не возвращает confidence напрямую
                    "duration_seconds": duration_seconds,
                    "cost_rub": cost_rub
                }
            else:
                logger.warning(f"Unexpected response format from SpeechKit: {result}")
                return {
                    "text": "",
                    "confidence": 0.0,
                    "duration_seconds": 0.0,
                    "cost_rub": 0.0
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling SpeechKit API: {e}", exc_info=True)
            raise Exception(f"Ошибка при транскрипции через SpeechKit: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in SpeechKit: {e}", exc_info=True)
            raise Exception(f"Неожиданная ошибка при транскрипции: {str(e)}")
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли SpeechKit"""
        return bool(self.folder_id and self.iam_token)
