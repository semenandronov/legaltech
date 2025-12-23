"""YandexGPT integration for LangChain using langchain-community (production-ready)"""
from typing import Optional
from langchain_community.chat_models.yandex import ChatYandexGPT as LangChainChatYandexGPT
from langchain_core.messages import SystemMessage, HumanMessage
import logging
from app.config import config

logger = logging.getLogger(__name__)


class ChatYandexGPT(LangChainChatYandexGPT):
    """
    Wrapper для ChatYandexGPT из langchain-community с автоматической конфигурацией
    
    Использует готовую реализацию из langchain-community, которая работает из коробки.
    Автоматически подставляет параметры из config.
    """
    
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        folder_id: Optional[str] = None,
        temperature: float = 0.1,
        **kwargs
    ):
        """
        Initialize YandexGPT using langchain-community implementation
        
        Args:
            model: Model name (default: yandexgpt-lite)
            api_key: Yandex API key or IAM token
            folder_id: Yandex Cloud folder ID
            temperature: Temperature for generation (default: 0.1 for legal analysis)
            **kwargs: Additional arguments passed to parent class
        """
        # Используем значения из config, если не указаны явно
        api_key = api_key or config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN
        folder_id = folder_id or config.YANDEX_FOLDER_ID
        
        # Определяем модель
        if model:
            model_name = model
        elif config.YANDEX_GPT_MODEL_URI:
            # Если указан полный URI, извлекаем короткое имя
            model_name = config.YANDEX_GPT_MODEL_URI.split("/")[-2] if "/" in config.YANDEX_GPT_MODEL_URI else config.YANDEX_GPT_MODEL
        else:
            model_name = config.YANDEX_GPT_MODEL or "yandexgpt-lite"
        
        # Убираем /latest если есть (langchain-community сам добавит)
        if "/" in model_name:
            model_name = model_name.split("/")[0]
        
        if not api_key:
            logger.warning("YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. YandexGPT will not work.")
        
        if not folder_id:
            logger.warning("YANDEX_FOLDER_ID not set. YandexGPT will not work.")
        
        # Инициализируем родительский класс из langchain-community
        super().__init__(
            model=model_name,
            api_key=api_key,
            folder_id=folder_id,
            temperature=temperature,
            **kwargs
        )
        
        logger.info(f"✅ Initialized ChatYandexGPT with model={model_name}, folder_id={folder_id[:8]}...")
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли YandexGPT"""
        return bool(self.api_key and self.folder_id)
