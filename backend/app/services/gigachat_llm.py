"""GigaChat integration for LangChain with function calling support"""
from typing import Optional, List, Any, Dict
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
import logging
from app.config import config

logger = logging.getLogger(__name__)

try:
    from gigachat import GigaChat as GigaChatSDK
    from gigachat.models import Chat, Messages, MessagesRole
    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False
    logger.warning("gigachat package not installed. Install with: pip install gigachat")


class ChatGigaChat(BaseChatModel):
    """
    Wrapper для GigaChat с поддержкой function calling через LangChain
    
    GigaChat поддерживает function calling, в отличие от YandexGPT!
    """
    
    credentials: str
    model: str = "GigaChat"
    temperature: float = 0.1
    verify_ssl_certs: bool = True
    _functions: Optional[List[Dict[str, Any]]] = None
    
    def __init__(
        self,
        credentials: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        verify_ssl_certs: bool = True,
        **kwargs
    ):
        """
        Initialize GigaChat
        
        Args:
            credentials: Authorization key (base64 encoded ClientID:ClientSecret)
                       SDK автоматически получает токен доступа из ключа авторизации.
                       Токен действителен 30 минут и автоматически обновляется.
            model: Model name (default: GigaChat)
            temperature: Temperature for generation
            verify_ssl_certs: Verify SSL certificates
        """
        if not GIGACHAT_AVAILABLE:
            raise ImportError(
                "gigachat package is not installed. "
                "Install it with: pip install gigachat"
            )
        
        # Используем credentials из config или переданные
        # Проверяем, что credentials не пустая строка
        final_credentials = credentials if credentials else config.GIGACHAT_CREDENTIALS
        final_model = model or config.GIGACHAT_MODEL or "GigaChat"
        
        if not final_credentials:
            raise ValueError("GIGACHAT_CREDENTIALS not set. Set GIGACHAT_CREDENTIALS in environment variables.")
        
        # Передаем все поля в super().__init__() для Pydantic валидации
        super().__init__(
            credentials=final_credentials,
            model=final_model,
            temperature=temperature,
            verify_ssl_certs=verify_ssl_certs,
            **kwargs
        )
        
        # Дополнительные поля, не входящие в Pydantic модель
        self._functions = None
        
        # Инициализируем GigaChat SDK
        try:
            self._client = GigaChatSDK(
                credentials=self.credentials,
                verify_ssl_certs=self.verify_ssl_certs
            )
            logger.info(f"✅ Initialized ChatGigaChat with model={self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize GigaChat: {e}", exc_info=True)
            raise
    
    @property
    def _llm_type(self) -> str:
        """Return type of LLM"""
        return "gigachat"
    
    def _convert_messages_to_gigachat(
        self, 
        messages: List[BaseMessage]
    ) -> List[Messages]:
        """Convert LangChain messages to GigaChat format"""
        gigachat_messages = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                gigachat_messages.append(
                    Messages(role=MessagesRole.SYSTEM, content=msg.content)
                )
            elif isinstance(msg, HumanMessage):
                gigachat_messages.append(
                    Messages(role=MessagesRole.USER, content=msg.content)
                )
            elif isinstance(msg, AIMessage):
                gigachat_messages.append(
                    Messages(role=MessagesRole.ASSISTANT, content=msg.content)
                )
        return gigachat_messages
    
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        Generate response from GigaChat
        
        Args:
            messages: List of messages
            stop: Stop sequences
            run_manager: Callback manager
            **kwargs: Additional arguments
        
        Returns:
            ChatResult with generated response
        """
        # Конвертируем LangChain messages в GigaChat format
        gigachat_messages = self._convert_messages_to_gigachat(messages)
        
        # Подготавливаем параметры для Chat
        # GigaChat SDK использует объект Chat с messages
        chat_obj = Chat(
            messages=gigachat_messages,
            temperature=self.temperature,
            model=self.model
        )
        
        # Добавляем functions если они есть (GigaChat поддерживает functions)
        if self._functions:
            # GigaChat SDK может принимать functions через отдельный параметр
            # Проверяем документацию SDK для правильного формата
            try:
                # Попробуем передать functions в chat
                response = self._client.chat(chat_obj, functions=self._functions)
            except TypeError:
                # Если не поддерживается через параметр, пробуем другой способ
                logger.warning("Functions parameter not supported in this SDK version, trying without")
                response = self._client.chat(chat_obj)
        else:
            response = self._client.chat(chat_obj)
        
        # Вызываем GigaChat API
        try:
            
            # Извлекаем ответ
            if response.choices and len(response.choices) > 0:
                message = response.choices[0].message
                content = message.content if hasattr(message, 'content') else ""
                
                # Проверяем, есть ли function calls
                function_calls = None
                if hasattr(message, 'function_calls') and message.function_calls:
                    function_calls = message.function_calls
                
                # Создаем LangChain message
                ai_message = AIMessage(content=content)
                
                # Добавляем tool_calls если есть
                if function_calls:
                    # Конвертируем function_calls в tool_calls формат LangChain
                    tool_calls = []
                    for fc in function_calls:
                        tool_calls.append({
                            "name": getattr(fc, 'name', ''),
                            "args": getattr(fc, 'arguments', {}),
                            "id": getattr(fc, 'id', '')
                        })
                    ai_message.tool_calls = tool_calls
                
                return ChatResult(
                    generations=[ChatGeneration(message=ai_message)]
                )
            else:
                # Пустой ответ
                return ChatResult(
                    generations=[ChatGeneration(message=AIMessage(content=""))]
                )
        except Exception as e:
            logger.error(f"Error calling GigaChat: {e}", exc_info=True)
            raise
    
    def bind_tools(
        self,
        tools: List[Any],
        **kwargs: Any
    ) -> "ChatGigaChat":
        """
        Bind tools to the model for function calling
        
        GigaChat поддерживает function calling!
        
        Args:
            tools: List of LangChain tools
            **kwargs: Additional arguments
        
        Returns:
            ChatGigaChat instance with tools bound
        """
        # Конвертируем LangChain tools в GigaChat functions format
        functions = []
        for tool in tools:
            try:
                # Получаем схему инструмента
                if hasattr(tool, 'name') and hasattr(tool, 'description'):
                    function_def = {
                        "name": tool.name,
                        "description": tool.description or "",
                    }
                    
                    # Пытаемся извлечь параметры из tool
                    parameters = {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                    
                    if hasattr(tool, 'args_schema') and tool.args_schema:
                        schema = tool.args_schema
                        if hasattr(schema, 'schema'):
                            json_schema = schema.schema()
                            if "properties" in json_schema:
                                parameters["properties"] = json_schema["properties"]
                            if "required" in json_schema:
                                parameters["required"] = json_schema["required"]
                    
                    function_def["parameters"] = parameters
                    functions.append(function_def)
            except Exception as e:
                logger.warning(f"Error converting tool {tool} to function: {e}")
                continue
        
        # Создаем новый экземпляр с функциями
        new_instance = ChatGigaChat(
            credentials=self.credentials,
            model=self.model,
            temperature=self.temperature,
            verify_ssl_certs=self.verify_ssl_certs
        )
        
        # Сохраняем функции для использования в _generate
        new_instance._functions = functions
        
        logger.info(f"✅ Bound {len(functions)} tools to GigaChat: {[f['name'] for f in functions]}")
        return new_instance
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли GigaChat"""
        return bool(self.credentials and hasattr(self, '_client') and self._client)
    
    def invoke(self, messages: List[BaseMessage], **kwargs) -> BaseMessage:
        """Invoke LLM and return message"""
        result = self._generate(messages, **kwargs)
        return result.generations[0].message

