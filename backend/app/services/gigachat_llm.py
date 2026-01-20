"""GigaChat integration for LangChain with function calling support"""
from typing import Optional, List, Any, Dict, Iterator
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.runnables import Runnable, RunnableConfig
import logging
from app.config import config

logger = logging.getLogger(__name__)

try:
    from gigachat import GigaChat as GigaChatSDK
    from gigachat.models import Chat, Messages, MessagesRole
    from gigachat.exceptions import ResponseError
    GIGACHAT_AVAILABLE = True
except ImportError:
    GIGACHAT_AVAILABLE = False
    logger.warning("gigachat package not installed. Install with: pip install gigachat")
    ResponseError = None


class ChatGigaChat(BaseChatModel):
    """
    Wrapper для GigaChat с поддержкой function calling через LangChain
    
    GigaChat поддерживает function calling!
    """
    
    credentials: str
    model: str = "GigaChat"
    temperature: float = 0.1
    verify_ssl_certs: bool = False  # Default to False for compatibility with Render/proxy environments
    timeout: float = 120.0  # Timeout для HTTP запросов (секунды)
    _functions: Optional[List[Dict[str, Any]]] = None
    
    def __init__(
        self,
        credentials: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.1,
        verify_ssl_certs: bool = False,  # Default to False for compatibility with Render/proxy environments
        timeout: float = 120.0,  # Timeout для HTTP запросов (секунды) - увеличен для сложных запросов
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
            timeout: HTTP request timeout in seconds (default: 120s for complex legal queries)
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
            timeout=timeout,
            **kwargs
        )
        
        # Дополнительные поля, не входящие в Pydantic модель
        self._functions = None
        
        # Инициализируем GigaChat SDK
        try:
            # Логируем настройки для диагностики
            logger.info(f"Initializing GigaChat with verify_ssl_certs={self.verify_ssl_certs}, timeout={self.timeout}s")
            
            self._client = GigaChatSDK(
                credentials=self.credentials,
                verify_ssl_certs=self.verify_ssl_certs,
                timeout=self.timeout  # Передаем timeout в SDK
            )
            logger.info(f"✅ Initialized ChatGigaChat with model={self.model}, verify_ssl={self.verify_ssl_certs}, timeout={self.timeout}s")
        except Exception as e:
            logger.error(f"Failed to initialize GigaChat: {e}", exc_info=True)
            # Если ошибка связана с SSL, предлагаем решение
            if "SSL" in str(e) or "certificate" in str(e).lower():
                logger.error(
                    "SSL certificate verification failed. "
                    "Set GIGACHAT_VERIFY_SSL=false in environment variables to disable SSL verification. "
                    "WARNING: This is less secure but may be necessary in some environments."
                )
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
        # В новых версиях SDK functions передаются в объект Chat, а не как параметр chat()
        chat_kwargs = {
            "messages": gigachat_messages,
            "temperature": self.temperature,
            "model": self.model
        }
        
        # Добавляем functions если есть - в объект Chat
        if self._functions:
            # Конвертируем functions в формат GigaChat SDK
            try:
                from gigachat.models import Function, FunctionParameters
                gigachat_functions = []
                for func in self._functions:
                    func_params = FunctionParameters(
                        type=func.get("parameters", {}).get("type", "object"),
                        properties=func.get("parameters", {}).get("properties", {}),
                        required=func.get("parameters", {}).get("required", [])
                    )
                    gigachat_func = Function(
                        name=func["name"],
                        description=func.get("description", ""),
                        parameters=func_params
                    )
                    gigachat_functions.append(gigachat_func)
                chat_kwargs["functions"] = gigachat_functions
                logger.info(f"[GigaChat] Added {len(gigachat_functions)} functions to Chat object")
            except ImportError as e:
                logger.warning(f"[GigaChat] Function/FunctionParameters not available in this SDK version: {e}")
            except Exception as e:
                logger.warning(f"[GigaChat] Failed to add functions to Chat: {e}")
        
        chat_obj = Chat(**chat_kwargs)
        
        # Вызываем GigaChat API with retry for rate limiting
        import time
        import random
        max_retries = 5  # Увеличиваем количество попыток
        retry_delay = 3  # Увеличиваем начальную задержку до 3 секунд
        response = None
        
        for attempt in range(max_retries):
            try:
                # Make API call
                response = self._client.chat(chat_obj)
                
                # If successful, break out of retry loop
                break
                
            except Exception as e:
                # Check if it's a 429 rate limit error
                is_rate_limit = (
                    ResponseError and isinstance(e, ResponseError) and 
                    hasattr(e, 'status_code') and e.status_code == 429
                ) or (
                    "429" in str(e) or "Too Many Requests" in str(e)
                )
                
                if is_rate_limit and attempt < max_retries - 1:
                    # Exponential backoff with jitter for rate limiting
                    # Увеличиваем время ожидания и добавляем случайную задержку для распределения нагрузки
                    base_wait = retry_delay * (2 ** attempt)
                    jitter = random.uniform(0.5, 1.5)  # Случайная задержка от 0.5 до 1.5
                    wait_time = base_wait * jitter
                    # Ограничиваем максимальное время ожидания до 30 секунд
                    wait_time = min(wait_time, 30.0)
                    
                    logger.warning(
                        f"Rate limit (429) hit, retrying in {wait_time:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Re-raise if not rate limit or out of retries
                    if is_rate_limit:
                        logger.error(
                            f"Rate limit (429) exceeded after {max_retries} attempts. "
                            f"Please reduce concurrent requests or wait before retrying."
                        )
                    raise
        
        # Извлекаем ответ
        if response is None:
            raise ValueError("Failed to get response from GigaChat after retries")
        
        try:
            if response.choices and len(response.choices) > 0:
                message = response.choices[0].message
                # Правильная обработка None content
                raw_content = getattr(message, 'content', None)
                content = str(raw_content) if raw_content is not None else ""
                
                # Логируем для диагностики
                logger.debug(f"[GigaChat] Response content: {content[:200] if content else '(empty)'}")
                
                # Проверяем, есть ли function calls
                function_calls = None
                if hasattr(message, 'function_calls') and message.function_calls:
                    function_calls = message.function_calls
                    logger.info(f"[GigaChat] Response has {len(function_calls)} function calls")
                
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
                logger.warning("[GigaChat] Empty response - no choices in response")
                return ChatResult(
                    generations=[ChatGeneration(message=AIMessage(content=""))]
                )
        except Exception as e:
            logger.error(f"Error calling GigaChat: {e}", exc_info=True)
            raise
    
    def _sanitize_property_for_gigachat(self, prop_name: str, prop_schema: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Преобразует property схему в формат совместимый с GigaChat API.
        
        GigaChat не поддерживает сложные типы (array, anyOf, allOf) без properties.
        Для таких типов мы либо упрощаем их до string, либо пропускаем.
        """
        # Если есть anyOf или allOf - это сложный тип, упрощаем до string
        if "anyOf" in prop_schema or "allOf" in prop_schema or "oneOf" in prop_schema:
            # Для Optional[List[str]] и подобных - делаем string с описанием
            description = prop_schema.get("description", "")
            return {
                "type": "string",
                "description": f"{description} (comma-separated values if multiple)"
            }
        
        prop_type = prop_schema.get("type")
        
        # Примитивные типы - оставляем как есть
        if prop_type in ("string", "integer", "number", "boolean"):
            return prop_schema
        
        # Array типы - преобразуем в string с comma-separated values
        if prop_type == "array":
            description = prop_schema.get("description", "")
            items = prop_schema.get("items", {})
            items_type = items.get("type", "string")
            return {
                "type": "string",
                "description": f"{description} (comma-separated list of {items_type}s)"
            }
        
        # Object типы без properties - пропускаем
        if prop_type == "object" and "properties" not in prop_schema:
            logger.warning(f"Skipping property '{prop_name}' - object without properties")
            return None
        
        # Остальное оставляем как есть
        return prop_schema
    
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
                                # Фильтруем и преобразуем properties для GigaChat
                                sanitized_props = {}
                                for prop_name, prop_schema in json_schema["properties"].items():
                                    sanitized = self._sanitize_property_for_gigachat(prop_name, prop_schema)
                                    if sanitized:
                                        sanitized_props[prop_name] = sanitized
                                parameters["properties"] = sanitized_props
                            if "required" in json_schema:
                                # Оставляем в required только те поля которые есть в properties
                                parameters["required"] = [
                                    r for r in json_schema["required"] 
                                    if r in parameters["properties"]
                                ]
                    
                    function_def["parameters"] = parameters
                    functions.append(function_def)
                    logger.debug(f"Tool '{tool.name}' converted: {len(parameters['properties'])} params")
            except Exception as e:
                logger.warning(f"Error converting tool {tool} to function: {e}")
                continue
        
        # Создаем новый экземпляр с функциями
        new_instance = ChatGigaChat(
            credentials=self.credentials,
            model=self.model,
            temperature=self.temperature,
            verify_ssl_certs=self.verify_ssl_certs,
            timeout=self.timeout
        )
        
        # Сохраняем функции для использования в _generate
        new_instance._functions = functions
        
        logger.info(f"✅ Bound {len(functions)} tools to GigaChat: {[f['name'] for f in functions]}")
        return new_instance
    
    def is_available(self) -> bool:
        """Проверяет, доступен ли GigaChat"""
        return bool(self.credentials and hasattr(self, '_client') and self._client)
    
    def with_structured_output(
        self,
        schema: Any,
        **kwargs
    ) -> "GigaChatStructuredOutput":
        """
        Создает обертку для structured output.
        
        GigaChat не поддерживает structured output нативно, поэтому мы:
        1. Добавляем инструкцию в промпт для JSON output
        2. Парсим JSON из ответа
        3. Валидируем через Pydantic модель
        
        Args:
            schema: Pydantic модель для валидации output
            **kwargs: Дополнительные аргументы (игнорируются)
        
        Returns:
            GigaChatStructuredOutput - обертка для structured output
        """
        return GigaChatStructuredOutput(self, schema)
    
    def invoke(
        self, 
        input: Any, 
        config: Optional[Any] = None,
        **kwargs
    ) -> BaseMessage:
        """
        Invoke LLM and return message.
        
        Соответствует интерфейсу LangChain Runnable для совместимости с 
        with_structured_output() и другими цепочками.
        
        Args:
            input: Сообщения (List[BaseMessage]) или другой input
            config: RunnableConfig (игнорируется, но принимается для совместимости)
            **kwargs: Дополнительные аргументы
        
        Returns:
            AIMessage с ответом модели
        """
        # Если input уже список сообщений - используем напрямую
        if isinstance(input, list):
            messages = input
        # Если input - это dict (например, от ChatPromptTemplate)
        elif isinstance(input, dict):
            # Пытаемся извлечь messages из dict
            messages = input.get("messages", [])
            if not messages:
                # Или создаем сообщение из text/content
                text = input.get("text") or input.get("content") or str(input)
                messages = [HumanMessage(content=text)]
        # Если input - строка
        elif isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            # Пробуем преобразовать в строку
            messages = [HumanMessage(content=str(input))]
        
        result = self._generate(messages, **kwargs)
        return result.generations[0].message


class GigaChatStructuredOutput(Runnable[Any, Any]):
    """
    Обертка для structured output через GigaChat.
    
    Наследует от LangChain Runnable для использования в цепочках (|).
    """
    
    llm: Any  # ChatGigaChat
    schema: Any  # Pydantic модель
    _schema_json: str = ""
    
    def __init__(self, llm: "ChatGigaChat", schema: Any, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, 'llm', llm)
        object.__setattr__(self, 'schema', schema)
        object.__setattr__(self, '_schema_json', self._get_schema_json_static(schema))
    
    @staticmethod
    def _get_schema_json_static(schema: Any) -> str:
        """Получает простой пример JSON из Pydantic модели (не полную схему!)"""
        # НЕ используем model_json_schema() - он возвращает сложную схему с $defs
        # Вместо этого создаем простой пример формата
        return ""  # Мы будем использовать фиксированный пример в _add_json_instruction
    
    def _add_json_instruction(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """Добавляет инструкцию для JSON output в системное сообщение"""
        # Инструкция для структурированного ответа - добавляется в конец последнего user сообщения
        json_instruction = """

--- ФОРМАТ ОТВЕТА ---
Ответь в формате JSON. Пример:
{"answer": "Твой ответ здесь. Ссылки на документы ставь как [1], [2].", "citations": [], "confidence": 0.8}

ВАЖНО:
- Поле "answer" ОБЯЗАТЕЛЬНО содержит твой текстовый ответ
- Используй [1], [2] и т.д. для ссылок на документы в тексте ответа
- citations - массив цитат, может быть пустым []
- Никакого текста ДО или ПОСЛЕ JSON!
"""
        
        # Добавляем инструкцию к ПОСЛЕДНЕМУ user сообщению (а не к системному)
        # Это лучше работает с GigaChat
        new_messages = list(messages)  # Копируем
        
        # Находим последнее HumanMessage и добавляем инструкцию
        for i in range(len(new_messages) - 1, -1, -1):
            if isinstance(new_messages[i], HumanMessage):
                new_content = new_messages[i].content + json_instruction
                new_messages[i] = HumanMessage(content=new_content)
                break
        else:
            # Если нет HumanMessage, добавляем как системное
            new_messages.insert(0, SystemMessage(content=json_instruction.strip()))
        
        return new_messages
    
    def _parse_json_from_response(self, content: str) -> Dict[str, Any]:
        """Извлекает JSON из ответа модели"""
        import json
        import re
        
        # Убираем возможные markdown блоки кода
        content = content.strip()
        if content.startswith("```"):
            # Убираем ```json или ``` в начале и ``` в конце
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
        
        # Пытаемся найти JSON объект в ответе
        # Ищем от первой { до последней }
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        
        # Пробуем распарсить весь контент как JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON from response: {e}")
            logger.debug(f"Response content: {content[:500]}")
            # Возвращаем пустой ответ как fallback
            return {"answer": content, "citations": [], "confidence": 0.0}
    
    def invoke(
        self, 
        input: Any, 
        config: Optional[RunnableConfig] = None,
        **kwargs
    ) -> Any:
        """
        Invoke LLM и вернуть structured output.
        
        Соответствует интерфейсу LangChain Runnable.
        
        Args:
            input: Входные данные (список сообщений, dict или строка)
            config: RunnableConfig (игнорируется, но принимается для совместимости)
            **kwargs: Дополнительные аргументы
        
        Returns:
            Экземпляр Pydantic модели (schema)
        """
        # Получаем сообщения из input
        if isinstance(input, list):
            messages = input
        elif isinstance(input, dict):
            messages = input.get("messages", [])
            if not messages:
                text = input.get("text") or input.get("content") or str(input)
                messages = [HumanMessage(content=text)]
        elif isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            messages = [HumanMessage(content=str(input))]
        
        # Добавляем JSON инструкцию
        messages_with_json = self._add_json_instruction(messages)
        
        # Вызываем LLM
        result = self.llm._generate(messages_with_json, **kwargs)
        ai_message = result.generations[0].message
        
        # Логируем сырой ответ для диагностики
        raw_content = ai_message.content
        logger.info(f"[GigaChat Structured] Raw response length: {len(raw_content)}")
        logger.debug(f"[GigaChat Structured] Raw response: {raw_content[:500]}...")
        
        # Парсим JSON из ответа
        json_data = self._parse_json_from_response(raw_content)
        logger.info(f"[GigaChat Structured] Parsed JSON keys: {list(json_data.keys()) if json_data else 'None'}")
        
        # Создаем и возвращаем экземпляр Pydantic модели
        try:
            # Проверяем, что есть поле answer
            if "answer" not in json_data or not json_data.get("answer"):
                # Если нет поля answer, используем весь контент как ответ
                logger.warning(f"[GigaChat Structured] No 'answer' field in response, using raw content")
                json_data["answer"] = raw_content
                json_data.setdefault("citations", [])
                json_data.setdefault("confidence", 0.5)
            
            if hasattr(self.schema, 'model_validate'):
                # Pydantic v2
                return self.schema.model_validate(json_data)
            else:
                # Pydantic v1
                return self.schema(**json_data)
        except Exception as e:
            logger.error(f"Failed to validate schema: {e}")
            # Возвращаем объект с минимальными данными - используем сырой контент
            return self.schema(
                answer=json_data.get("answer") or raw_content,
                citations=json_data.get("citations", []),
                confidence=json_data.get("confidence", 0.0)
            )

