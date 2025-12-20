"""YandexGPT Embeddings for LangChain using official Yandex Cloud ML SDK"""
from typing import List, Any, Optional
import logging
from langchain_core.embeddings import Embeddings
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
from app.config import config

logger = logging.getLogger(__name__)


class YandexEmbeddings(Embeddings):
    """YandexGPT embeddings for LangChain using official SDK"""
    
    sdk: Any = None  # Добавляем поле sdk
    
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
                # SDK требует folder_id - если не указан, не инициализируем
                logger.warning("YANDEX_FOLDER_ID not set, Yandex embeddings will not work. Using OpenAI fallback.")
                self.sdk = None
                return
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
            # Используем полный URI из конфига, если указан
            embedding_model_uri = getattr(config, 'YANDEX_EMBEDDING_MODEL_URI', '')
            embedding_model_name = embedding_model_uri or getattr(config, 'YANDEX_EMBEDDING_MODEL', 'text-search-query')
            
            # Если model_name не полный URI и folder_id есть, формируем полный URI
            if not embedding_model_name.startswith("emb://") and self.folder_id:
                # Формируем полный URI из короткого имени
                # Добавляем /latest если версия не указана
                if "/" in embedding_model_name:
                    # Уже есть версия (например, text-search-query/latest)
                    model_name_to_use = f"emb://{self.folder_id}/{embedding_model_name}"
                else:
                    # Только имя модели, добавляем /latest
                    model_name_to_use = f"emb://{self.folder_id}/{embedding_model_name}/latest"
                logger.info(f"Converted short embedding model name to full URI: {model_name_to_use}")
            elif embedding_model_name.startswith("emb://"):
                model_name_to_use = embedding_model_name
                logger.debug(f"Using full embedding model URI: {model_name_to_use}")
            else:
                model_name_to_use = embedding_model_name
                logger.warning(f"Using short embedding model name without folder_id (may fail): {model_name_to_use}")
            
            # Получаем модель embeddings
            embeddings_model = self.sdk.models.text_embeddings(model_name_to_use)
            
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
