"""
Base Protocol - Базовый протокол для всех агентов

Определяет единый интерфейс для агентов системы:
- execute: синхронное выполнение
- stream: асинхронное выполнение с streaming
- validate_input: валидация входных данных
"""
from typing import Protocol, AsyncGenerator, Any, Dict, Optional, List, runtime_checkable
from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum


class AgentStatus(Enum):
    """Статус выполнения агента"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass
class AgentResult:
    """Результат выполнения агента"""
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None
    
    @classmethod
    def success_result(cls, output: Any, metadata: Optional[Dict[str, Any]] = None) -> "AgentResult":
        """Создать успешный результат"""
        return cls(success=True, output=output, metadata=metadata)
    
    @classmethod
    def error_result(cls, error: str, metadata: Optional[Dict[str, Any]] = None) -> "AgentResult":
        """Создать результат с ошибкой"""
        return cls(success=False, output=None, error=error, metadata=metadata)


@dataclass
class AgentEvent:
    """Событие от агента (для streaming)"""
    event_type: str
    data: Any
    agent_name: str
    timestamp: Optional[float] = None


@runtime_checkable
class AgentProtocol(Protocol):
    """
    Базовый протокол для всех агентов.
    
    Каждый агент должен реализовать:
    - name: уникальное имя агента
    - description: описание функциональности
    - execute: синхронное выполнение
    - stream: асинхронное выполнение с streaming
    - validate_input: валидация входных данных
    """
    
    @property
    def name(self) -> str:
        """Уникальное имя агента"""
        ...
    
    @property
    def description(self) -> str:
        """Описание функциональности агента"""
        ...
    
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить агента
        
        Args:
            state: Текущее состояние (AnalysisState или подобное)
            
        Returns:
            Обновлённое состояние
        """
        ...
    
    async def stream(self, state: Dict[str, Any]) -> AsyncGenerator[AgentEvent, None]:
        """
        Выполнить агента с streaming событий
        
        Args:
            state: Текущее состояние
            
        Yields:
            AgentEvent события
        """
        ...
    
    def validate_input(self, state: Dict[str, Any]) -> bool:
        """
        Валидировать входные данные
        
        Args:
            state: Состояние для валидации
            
        Returns:
            True если валидно, False иначе
        """
        ...


class BaseAgent:
    """
    Базовый класс для агентов.
    
    Предоставляет общую функциональность:
    - Логирование
    - Обработка ошибок
    - Метрики выполнения
    """
    
    def __init__(self, name: str, description: str = ""):
        """
        Инициализация агента
        
        Args:
            name: Уникальное имя агента
            description: Описание функциональности
        """
        self._name = name
        self._description = description
        self._status = AgentStatus.PENDING
        
        import logging
        self.logger = logging.getLogger(f"agent.{name}")
    
    @property
    def name(self) -> str:
        """Уникальное имя агента"""
        return self._name
    
    @property
    def description(self) -> str:
        """Описание функциональности агента"""
        return self._description
    
    @property
    def status(self) -> AgentStatus:
        """Текущий статус агента"""
        return self._status
    
    def validate_input(self, state: Dict[str, Any]) -> bool:
        """
        Валидировать входные данные (базовая реализация)
        
        Override в подклассах для специфичной валидации.
        """
        return True
    
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Выполнить агента
        
        Базовая реализация с логированием и обработкой ошибок.
        Override _execute в подклассах.
        """
        import time
        start_time = time.time()
        
        self._status = AgentStatus.RUNNING
        self.logger.info(f"Starting execution")
        
        try:
            # Валидация
            if not self.validate_input(state):
                self._status = AgentStatus.FAILED
                self.logger.error("Input validation failed")
                return self._add_error_to_state(state, "Input validation failed")
            
            # Выполнение
            result = await self._execute(state)
            
            self._status = AgentStatus.COMPLETED
            execution_time = (time.time() - start_time) * 1000
            self.logger.info(f"Execution completed in {execution_time:.2f}ms")
            
            return result
            
        except Exception as e:
            self._status = AgentStatus.FAILED
            self.logger.error(f"Execution failed: {e}", exc_info=True)
            return self._add_error_to_state(state, str(e))
    
    async def _execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Внутренняя реализация выполнения.
        
        Override в подклассах.
        """
        raise NotImplementedError("Subclasses must implement _execute")
    
    async def stream(self, state: Dict[str, Any]) -> AsyncGenerator[AgentEvent, None]:
        """
        Выполнить агента с streaming событий.
        
        Базовая реализация - один event в конце.
        Override _stream в подклассах для полноценного streaming.
        """
        import time
        
        self._status = AgentStatus.RUNNING
        
        try:
            # Отправляем событие о начале
            yield AgentEvent(
                event_type="start",
                data={"message": f"Agent {self.name} started"},
                agent_name=self.name,
                timestamp=time.time()
            )
            
            # Выполняем с streaming
            async for event in self._stream(state):
                yield event
            
            self._status = AgentStatus.COMPLETED
            
            # Отправляем событие о завершении
            yield AgentEvent(
                event_type="complete",
                data={"message": f"Agent {self.name} completed"},
                agent_name=self.name,
                timestamp=time.time()
            )
            
        except Exception as e:
            self._status = AgentStatus.FAILED
            self.logger.error(f"Stream failed: {e}", exc_info=True)
            
            yield AgentEvent(
                event_type="error",
                data={"error": str(e)},
                agent_name=self.name,
                timestamp=time.time()
            )
    
    async def _stream(self, state: Dict[str, Any]) -> AsyncGenerator[AgentEvent, None]:
        """
        Внутренняя реализация streaming.
        
        Базовая реализация - просто вызывает execute.
        Override в подклассах для полноценного streaming.
        """
        import time
        
        result = await self._execute(state)
        
        yield AgentEvent(
            event_type="result",
            data=result,
            agent_name=self.name,
            timestamp=time.time()
        )
    
    def _add_error_to_state(self, state: Dict[str, Any], error: str) -> Dict[str, Any]:
        """Добавить ошибку в состояние"""
        errors = state.get("errors", [])
        errors.append(f"[{self.name}] {error}")
        return {**state, "errors": errors}


class ToolEnabledAgent(BaseAgent):
    """
    Агент с поддержкой инструментов.
    
    Расширяет BaseAgent:
    - Регистрация инструментов
    - Вызов инструментов
    - Обработка результатов инструментов
    """
    
    def __init__(self, name: str, description: str = "", tools: Optional[List[Any]] = None):
        """
        Инициализация агента с инструментами
        
        Args:
            name: Уникальное имя агента
            description: Описание функциональности
            tools: Список инструментов
        """
        super().__init__(name, description)
        self._tools = tools or []
        self._tool_map: Dict[str, Any] = {}
        
        # Индексируем инструменты по имени
        for tool in self._tools:
            tool_name = getattr(tool, 'name', None) or str(tool)
            self._tool_map[tool_name] = tool
    
    @property
    def tools(self) -> List[Any]:
        """Список инструментов агента"""
        return self._tools
    
    def add_tool(self, tool: Any) -> None:
        """Добавить инструмент"""
        tool_name = getattr(tool, 'name', None) or str(tool)
        self._tools.append(tool)
        self._tool_map[tool_name] = tool
    
    def get_tool(self, name: str) -> Optional[Any]:
        """Получить инструмент по имени"""
        return self._tool_map.get(name)
    
    async def invoke_tool(self, tool_name: str, **kwargs) -> Any:
        """
        Вызвать инструмент
        
        Args:
            tool_name: Имя инструмента
            **kwargs: Аргументы инструмента
            
        Returns:
            Результат инструмента
            
        Raises:
            ValueError: Если инструмент не найден
        """
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        
        self.logger.debug(f"Invoking tool: {tool_name}")
        
        # Поддержка разных типов инструментов
        if hasattr(tool, 'ainvoke'):
            return await tool.ainvoke(kwargs)
        elif hasattr(tool, 'invoke'):
            return tool.invoke(kwargs)
        elif callable(tool):
            return tool(**kwargs)
        else:
            raise ValueError(f"Tool {tool_name} is not callable")


class LLMAgent(ToolEnabledAgent):
    """
    Агент с LLM.
    
    Расширяет ToolEnabledAgent:
    - Интеграция с LLM
    - Управление промптами
    - Structured output
    """
    
    def __init__(
        self,
        name: str,
        description: str = "",
        tools: Optional[List[Any]] = None,
        llm: Optional[Any] = None,
        system_prompt: Optional[str] = None
    ):
        """
        Инициализация LLM агента
        
        Args:
            name: Уникальное имя агента
            description: Описание функциональности
            tools: Список инструментов
            llm: LLM для генерации
            system_prompt: Системный промпт
        """
        super().__init__(name, description, tools)
        self._llm = llm
        self._system_prompt = system_prompt
    
    @property
    def llm(self) -> Optional[Any]:
        """LLM агента"""
        return self._llm
    
    @property
    def system_prompt(self) -> Optional[str]:
        """Системный промпт"""
        return self._system_prompt
    
    def set_llm(self, llm: Any) -> None:
        """Установить LLM"""
        self._llm = llm
    
    def set_system_prompt(self, prompt: str) -> None:
        """Установить системный промпт"""
        self._system_prompt = prompt
    
    async def generate(self, messages: List[Any], **kwargs) -> Any:
        """
        Генерация через LLM
        
        Args:
            messages: Список сообщений
            **kwargs: Дополнительные параметры
            
        Returns:
            Ответ LLM
        """
        if not self._llm:
            raise ValueError("LLM not configured")
        
        # Добавляем системный промпт если есть
        if self._system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=self._system_prompt)] + list(messages)
        
        if hasattr(self._llm, 'ainvoke'):
            return await self._llm.ainvoke(messages, **kwargs)
        else:
            return self._llm.invoke(messages, **kwargs)
    
    async def generate_with_tools(self, messages: List[Any], **kwargs) -> Any:
        """
        Генерация с инструментами
        
        Args:
            messages: Список сообщений
            **kwargs: Дополнительные параметры
            
        Returns:
            Ответ LLM (может содержать tool calls)
        """
        if not self._llm:
            raise ValueError("LLM not configured")
        
        # Привязываем инструменты к LLM
        llm_with_tools = self._llm
        if self._tools and hasattr(self._llm, 'bind_tools'):
            llm_with_tools = self._llm.bind_tools(self._tools)
        
        # Добавляем системный промпт
        if self._system_prompt:
            from langchain_core.messages import SystemMessage
            messages = [SystemMessage(content=self._system_prompt)] + list(messages)
        
        if hasattr(llm_with_tools, 'ainvoke'):
            return await llm_with_tools.ainvoke(messages, **kwargs)
        else:
            return llm_with_tools.invoke(messages, **kwargs)


