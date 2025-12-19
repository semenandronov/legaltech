"""YandexGPT Embeddings for LangChain using official Yandex Cloud ML SDK"""
from typing import List
import logging
from langchain_core.embeddings import Embeddings
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
from app.config import config

logger = logging.getLogger(__name__)


class YandexEmbeddings(Embeddings):
    """YandexGPT embeddings for LangChain using official SDK"""
    
    def __init__(self, **kwargs):
        """Initialize Yandex embeddings using official SDK"""
        # Поддерживаем оба варианта: API ключ (приоритет) или IAM токен
        self.api_key = kwargs.get("api_key", config.YANDEX_API_KEY)
        self.iam_token = kwargs.get("iam_token", config.YANDEX_IAM_TOKEN)
        self.folder_id = kwargs.get("folder_id", config.YANDEX_FOLDER_ID)
        
        # Инициализируем SDK
        auth = None
        if self.api_key:
            auth = APIKeyAuth(self.api_key)
            logger.info("✅ Using Yandex API key for embeddings")
        elif self.iam_token:
            auth = self.iam_token
            logger.info("✅ Using Yandex IAM token for embeddings")
        else:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. "
                "Yandex embeddings will not work."
            )
            self.sdk = None
            return
        
        # Создаем SDK экземпляр
        try:
            if self.folder_id:
                self.sdk = YCloudML(folder_id=self.folder_id, auth=auth)
            else:
                # SDK может работать без folder_id если он встроен в API ключ
                self.sdk = YCloudML(auth=auth)
                logger.warning("YANDEX_FOLDER_ID not set, SDK will try to use folder from auth")
        except Exception as e:
            logger.error(f"Failed to initialize Yandex Cloud ML SDK: {e}", exc_info=True)
            self.sdk = None
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed documents using YandexGPT via official SDK
        
        Args:
            texts: List of texts to embed
        
        Returns:
            List of embedding vectors
        """
        if not self.sdk:
            raise ValueError(
                "Yandex Cloud ML SDK not initialized. "
                "Check YANDEX_API_KEY or YANDEX_IAM_TOKEN in .env file"
            )
        
        embeddings = []
        
        try:
            # Получаем модель embeddings
            embeddings_model = self.sdk.models.text_embeddings('yandexgpt')
            
            # Обрабатываем каждый текст
            for text in texts:
                try:
                    logger.debug(f"Embedding text (length: {len(text)}) via SDK")
                    
                    # Вызываем модель через SDK
                    result = embeddings_model.run(text)
                    
                    # Извлекаем embedding вектор
                    if result and hasattr(result, 'embedding'):
                        embedding = result.embedding
                        embeddings.append(embedding)
                    else:
                        logger.warning(f"Unexpected result format from Yandex embeddings SDK: {result}")
                        # Возвращаем нулевой вектор в случае ошибки
                        embeddings.append([0.0] * 256)  # Yandex embeddings обычно 256 размерности
                        
                except Exception as e:
                    logger.error(f"Error embedding text via SDK: {e}", exc_info=True)
                    # Возвращаем нулевой вектор в случае ошибки
                    embeddings.append([0.0] * 256)
                    
        except Exception as e:
            logger.error(f"Error initializing embeddings model: {e}", exc_info=True)
            # Возвращаем нулевые векторы для всех текстов
            embeddings = [[0.0] * 256] * len(texts)
        
        return embeddings
    
    def embed_query(self, text: str) -> List[float]:
        """
        Embed a single query text
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector
        """
        embeddings = self.embed_documents([text])
        return embeddings[0] if embeddings else [0.0] * 256
    
    def is_available(self) -> bool:
        """Проверяет, доступны ли Yandex embeddings"""
        return bool(self.sdk is not None)
