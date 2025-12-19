"""YandexGPT integration for LangChain using official Yandex Cloud ML SDK"""
from typing import Any, List, Optional, Dict
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.callbacks import CallbackManagerForLLMRun
from yandex_cloud_ml_sdk import YCloudML
from yandex_cloud_ml_sdk.auth import APIKeyAuth
import logging
from app.config import config

logger = logging.getLogger(__name__)


class ChatYandexGPT(BaseChatModel):
    """YandexGPT chat model for LangChain using official SDK"""
    
    model_name: str = "yandexgpt-pro/latest"
    folder_id: str = ""
    api_key: str = ""
    iam_token: str = ""
    temperature: float = 0.7
    max_tokens: int = 2000
    
    def __init__(self, **kwargs):
        """Initialize YandexGPT using official SDK"""
        super().__init__(**kwargs)
        self.folder_id = kwargs.get("folder_id", config.YANDEX_FOLDER_ID)
        self.api_key = kwargs.get("api_key", config.YANDEX_API_KEY)
        self.iam_token = kwargs.get("iam_token", config.YANDEX_IAM_TOKEN)
        self.model_name = kwargs.get("model_name", config.YANDEX_GPT_MODEL)
        self.temperature = kwargs.get("temperature", 0.7)
        self.max_tokens = kwargs.get("max_tokens", 2000)
        
        # Инициализируем SDK
        auth = None
        if self.api_key:
            auth = APIKeyAuth(self.api_key)
            logger.info("✅ Using Yandex API key for authentication")
        elif self.iam_token:
            auth = self.iam_token
            logger.info("✅ Using Yandex IAM token for authentication")
        else:
            logger.warning(
                "YANDEX_API_KEY or YANDEX_IAM_TOKEN not set. "
                "YandexGPT will not work."
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
    
    @property
    def _llm_type(self) -> str:
        """Return type of LLM"""
        return "yandexgpt"
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate response from YandexGPT using official SDK"""
        if not self.sdk:
            raise ValueError(
                "Yandex Cloud ML SDK not initialized. "
                "Check YANDEX_API_KEY or YANDEX_IAM_TOKEN in .env file"
            )
        
        try:
            # Получаем модель completions
            model = self.sdk.models.completions(self.model_name)
            
            # Настраиваем параметры
            model = model.configure(
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            # Конвертируем сообщения LangChain в формат SDK
            # SDK completions принимает строку или список сообщений
            # Для chat используем список сообщений
            conversation_messages = self._format_messages_for_sdk(messages)
            
            logger.debug(f"Calling YandexGPT via SDK with {len(messages)} messages")
            
            # Вызываем модель - SDK может принимать как строку, так и список сообщений
            # Попробуем сначала список сообщений (для chat), если не сработает - строку
            try:
                result = model.run(conversation_messages)
            except Exception as e:
                # Fallback: если SDK не принимает список, конвертируем в строку
                logger.debug(f"SDK didn't accept message list, trying string format: {e}")
                conversation_text = self._format_messages_as_text(messages)
                result = model.run(conversation_text)
            
            # Извлекаем ответ
            if result and len(result) > 0:
                # SDK возвращает список альтернатив
                text = str(result[0])  # Берем первую альтернативу
                
                # Создаем ChatResult
                generation = ChatGeneration(
                    message=AIMessage(content=text)
                )
                return ChatResult(generations=[generation])
            else:
                logger.warning("Empty result from YandexGPT SDK")
                raise Exception("Получен пустой ответ от YandexGPT")
                
        except Exception as e:
            logger.error(f"Error calling YandexGPT via SDK: {e}", exc_info=True)
            raise Exception(f"Ошибка при вызове YandexGPT: {str(e)}")
    
    def _format_messages_for_sdk(self, messages: List[BaseMessage]) -> List[Dict]:
        """
        Форматирует сообщения LangChain в список словарей для SDK
        
        Args:
            messages: Список сообщений LangChain
        
        Returns:
            Список словарей в формате SDK
        """
        formatted_messages = []
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                # System messages могут быть переданы отдельно
                continue  # SDK может не поддерживать system messages напрямую
            elif isinstance(msg, HumanMessage):
                formatted_messages.append({
                    "role": "user",
                    "text": msg.content
                })
            elif isinstance(msg, AIMessage):
                formatted_messages.append({
                    "role": "assistant",
                    "text": msg.content
                })
            else:
                # Fallback для других типов сообщений
                formatted_messages.append({
                    "role": "user",
                    "text": str(msg.content)
                })
        
        return formatted_messages
    
    def _format_messages_as_text(self, messages: List[BaseMessage]) -> str:
        """
        Форматирует сообщения LangChain в текст для SDK (fallback)
        
        Args:
            messages: Список сообщений LangChain
        
        Returns:
            Форматированный текст для completions
        """
        formatted_parts = []
        
        for msg in messages:
            if isinstance(msg, SystemMessage):
                formatted_parts.append(f"System: {msg.content}")
            elif isinstance(msg, HumanMessage):
                formatted_parts.append(f"User: {msg.content}")
            elif isinstance(msg, AIMessage):
                formatted_parts.append(f"Assistant: {msg.content}")
            else:
                formatted_parts.append(str(msg.content))
        
        return "\n\n".join(formatted_parts)
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли YandexGPT"""
        return bool(self.sdk is not None)
