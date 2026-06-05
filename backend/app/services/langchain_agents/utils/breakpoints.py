"""
Утилиты для Breakpoints в LangGraph.

Breakpoints позволяют:
- Прерывать выполнение графа перед/после определённых узлов
- Динамически прерывать выполнение на основе условий
- Редактировать состояние на точках прерывания

Типы breakpoints:
1. Static breakpoints: interrupt_before/interrupt_after в compile()
2. Dynamic breakpoints: NodeInterrupt в узлах на основе условий

Примеры использования:
```python
from app.services.langchain_agents.utils.breakpoints import (
    BreakpointConfig,
    create_breakpoint_config,
    should_interrupt,
    NodeInterrupt,
)

# Конфигурация breakpoints
config = create_breakpoint_config(
    interrupt_before=["generate_response"],
    interrupt_after=["rag_retrieval"]
)

# Динамический breakpoint в узле
def my_node(state):
    if state.get("confidence", 1.0) < 0.5:
        raise NodeInterrupt("Low confidence", state)
    # ...
```
"""
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class BreakpointType(str, Enum):
    """Типы breakpoints."""
    BEFORE = "before"  # Прерывание перед узлом
    AFTER = "after"    # Прерывание после узла
    DYNAMIC = "dynamic"  # Динамическое прерывание


@dataclass
class BreakpointConfig:
    """
    Конфигурация breakpoints для графа.
    
    Attributes:
        interrupt_before: Узлы для прерывания перед выполнением
        interrupt_after: Узлы для прерывания после выполнения
        conditions: Условия для динамических breakpoints
        enabled: Включены ли breakpoints
    """
    interrupt_before: List[str] = field(default_factory=list)
    interrupt_after: List[str] = field(default_factory=list)
    conditions: Dict[str, Callable[[Dict[str, Any]], bool]] = field(default_factory=dict)
    enabled: bool = True
    
    def to_compile_kwargs(self) -> Dict[str, Any]:
        """
        Преобразовать в kwargs для graph.compile().
        
        Returns:
            Словарь с interrupt_before и interrupt_after
        """
        kwargs = {}
        if self.interrupt_before:
            kwargs["interrupt_before"] = self.interrupt_before
        if self.interrupt_after:
            kwargs["interrupt_after"] = self.interrupt_after
        return kwargs


class NodeInterrupt(Exception):
    """
    Исключение для динамического прерывания узла.
    
    Используется внутри узлов для прерывания выполнения
    на основе условий состояния.
    
    Example:
        >>> def my_node(state):
        ...     if state.get("needs_approval"):
        ...         raise NodeInterrupt(
        ...             "Требуется одобрение",
        ...             state,
        ...             interrupt_type="approval"
        ...         )
    """
    
    def __init__(
        self,
        message: str,
        state: Dict[str, Any] = None,
        interrupt_type: str = "generic",
        metadata: Dict[str, Any] = None
    ):
        """
        Инициализация.
        
        Args:
            message: Сообщение о причине прерывания
            state: Текущее состояние
            interrupt_type: Тип прерывания (для обработки на клиенте)
            metadata: Дополнительные метаданные
        """
        super().__init__(message)
        self.message = message
        self.state = state or {}
        self.interrupt_type = interrupt_type
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для сериализации."""
        return {
            "type": "node_interrupt",
            "message": self.message,
            "interrupt_type": self.interrupt_type,
            "metadata": self.metadata,
            "state_keys": list(self.state.keys())
        }


def create_breakpoint_config(
    interrupt_before: List[str] = None,
    interrupt_after: List[str] = None,
    conditions: Dict[str, Callable[[Dict[str, Any]], bool]] = None,
    enabled: bool = True
) -> BreakpointConfig:
    """
    Создать конфигурацию breakpoints.
    
    Args:
        interrupt_before: Узлы для прерывания перед выполнением
        interrupt_after: Узлы для прерывания после выполнения
        conditions: Условия для динамических breakpoints
        enabled: Включены ли breakpoints
    
    Returns:
        BreakpointConfig
    """
    return BreakpointConfig(
        interrupt_before=interrupt_before or [],
        interrupt_after=interrupt_after or [],
        conditions=conditions or {},
        enabled=enabled
    )


def should_interrupt(
    state: Dict[str, Any],
    condition: Callable[[Dict[str, Any]], bool]
) -> bool:
    """
    Проверить, нужно ли прервать выполнение.
    
    Args:
        state: Текущее состояние
        condition: Функция-условие
    
    Returns:
        True если нужно прервать
    """
    try:
        return condition(state)
    except Exception as e:
        logger.warning(f"[Breakpoints] Condition check error: {e}")
        return False


# ============== Предопределённые условия ==============

def low_confidence_condition(threshold: float = 0.5) -> Callable[[Dict[str, Any]], bool]:
    """
    Условие: низкая уверенность.
    
    Args:
        threshold: Порог уверенности
    
    Returns:
        Функция-условие
    """
    def check(state: Dict[str, Any]) -> bool:
        confidence = state.get("confidence", 1.0)
        return confidence < threshold
    return check


def has_errors_condition() -> Callable[[Dict[str, Any]], bool]:
    """
    Условие: есть ошибки в состоянии.
    
    Returns:
        Функция-условие
    """
    def check(state: Dict[str, Any]) -> bool:
        errors = state.get("errors")
        return bool(errors)
    return check


def missing_context_condition(context_keys: List[str]) -> Callable[[Dict[str, Any]], bool]:
    """
    Условие: отсутствует контекст.
    
    Args:
        context_keys: Ключи контекста для проверки
    
    Returns:
        Функция-условие
    """
    def check(state: Dict[str, Any]) -> bool:
        for key in context_keys:
            value = state.get(key)
            if value is None or value == "":
                return True
        return False
    return check


def clarification_needed_condition() -> Callable[[Dict[str, Any]], bool]:
    """
    Условие: нужно уточнение.
    
    Returns:
        Функция-условие
    """
    def check(state: Dict[str, Any]) -> bool:
        requests = state.get("clarification_requests", [])
        return len(requests) > 0
    return check


def approval_required_condition() -> Callable[[Dict[str, Any]], bool]:
    """
    Условие: требуется одобрение.
    
    Returns:
        Функция-условие
    """
    def check(state: Dict[str, Any]) -> bool:
        return state.get("require_approval", False) and not state.get("plan_approved", False)
    return check


# ============== Декораторы для узлов ==============

def with_breakpoint(
    condition: Callable[[Dict[str, Any]], bool],
    message: str = "Breakpoint triggered",
    interrupt_type: str = "conditional"
):
    """
    Декоратор для добавления динамического breakpoint к узлу.
    
    Args:
        condition: Функция-условие
        message: Сообщение при прерывании
        interrupt_type: Тип прерывания
    
    Returns:
        Декоратор
    
    Example:
        >>> @with_breakpoint(low_confidence_condition(0.5), "Low confidence")
        ... def my_node(state):
        ...     return state
    """
    def decorator(func):
        def wrapper(state: Dict[str, Any], *args, **kwargs):
            # Проверяем условие перед выполнением
            if should_interrupt(state, condition):
                raise NodeInterrupt(message, state, interrupt_type)
            
            # Выполняем узел
            return func(state, *args, **kwargs)
        
        return wrapper
    return decorator


def with_breakpoint_after(
    condition: Callable[[Dict[str, Any]], bool],
    message: str = "Breakpoint triggered after",
    interrupt_type: str = "conditional_after"
):
    """
    Декоратор для добавления breakpoint после выполнения узла.
    
    Args:
        condition: Функция-условие
        message: Сообщение при прерывании
        interrupt_type: Тип прерывания
    
    Returns:
        Декоратор
    """
    def decorator(func):
        def wrapper(state: Dict[str, Any], *args, **kwargs):
            # Выполняем узел
            result = func(state, *args, **kwargs)
            
            # Проверяем условие после выполнения
            if should_interrupt(result, condition):
                raise NodeInterrupt(message, result, interrupt_type)
            
            return result
        
        return wrapper
    return decorator


# ============== Конфигурации для графов ==============

# Конфигурация breakpoints для ChatGraph
CHAT_GRAPH_BREAKPOINTS = create_breakpoint_config(
    interrupt_before=[],  # По умолчанию не прерываем
    interrupt_after=[],
    conditions={
        "low_confidence": low_confidence_condition(0.5),
        "has_errors": has_errors_condition(),
    }
)

# Конфигурация breakpoints для WorkflowGraph
WORKFLOW_GRAPH_BREAKPOINTS = create_breakpoint_config(
    interrupt_before=[],
    interrupt_after=["generate_plan"],  # Прерываем после генерации плана
    conditions={
        "approval_required": approval_required_condition(),
        "has_errors": has_errors_condition(),
    }
)


def get_breakpoint_config_for_graph(graph_name: str) -> BreakpointConfig:
    """
    Получить конфигурацию breakpoints для графа.
    
    Args:
        graph_name: Имя графа ("chat", "workflow")
    
    Returns:
        BreakpointConfig
    """
    configs = {
        "chat": CHAT_GRAPH_BREAKPOINTS,
        "workflow": WORKFLOW_GRAPH_BREAKPOINTS,
    }
    return configs.get(graph_name, create_breakpoint_config())

