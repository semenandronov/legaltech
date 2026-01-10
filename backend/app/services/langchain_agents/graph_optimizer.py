"""Graph optimizer utilities for LangGraph - оптимизация conditional edges и роутинга"""
from typing import Dict, Any, List, Optional, Callable, Union
from functools import lru_cache
from app.services.langchain_agents.state import AnalysisState
import logging
import hashlib
import json
import time

# Try to import Command
try:
    from langgraph.types import Command
    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None

logger = logging.getLogger(__name__)


class RouteCache:
    """Кэш для решений роутинга с автоматической инвалидацией"""
    
    def __init__(self, max_size: int = 100):
        self.cache: Dict[str, str] = {}
        self.max_size = max_size
        self.access_order: List[str] = []  # Для LRU eviction
        
    def _make_key(self, state: AnalysisState) -> str:
        """Создает ключ кэша на основе релевантных полей состояния"""
        # Включаем только поля, влияющие на роутинг
        key_data = {
            "case_id": state.get("case_id"),
            "analysis_types": sorted(state.get("analysis_types", [])),
            "completed": self._get_completed_agents(state),
            "waiting_for_human": state.get("waiting_for_human", False),
            "needs_replanning": state.get("needs_replanning", False),
            "current_plan": state.get("current_plan", []),
            "subtasks": state.get("subtasks", []),
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_completed_agents(self, state: AnalysisState) -> List[str]:
        """Извлекает список завершенных агентов из состояния"""
        completed = []
        if state.get("timeline_result"):
            completed.append("timeline")
        if state.get("key_facts_result"):
            completed.append("key_facts")
        if state.get("discrepancy_result"):
            completed.append("discrepancy")
        if state.get("risk_result"):
            completed.append("risk")
        if state.get("summary_result"):
            completed.append("summary")
        if state.get("classification_result"):
            completed.append("document_classifier")
        if state.get("entities_result"):
            completed.append("entity_extraction")
        if state.get("privilege_result"):
            completed.append("privilege_check")
        if state.get("relationship_result"):
            completed.append("relationship")
        if state.get("deep_analysis_result"):
            completed.append("deep_analysis")
        return sorted(completed)
    
    def get(self, state: AnalysisState) -> Optional[str]:
        """Получить кэшированный маршрут"""
        key = self._make_key(state)
        if key in self.cache:
            # Обновляем порядок доступа (LRU)
            self.access_order.remove(key)
            self.access_order.append(key)
            logger.debug(f"[RouteCache] Cache hit for key {key[:8]}")
            return self.cache[key]
        logger.debug(f"[RouteCache] Cache miss for key {key[:8]}")
        return None
    
    def set(self, state: AnalysisState, route: str):
        """Сохранить маршрут в кэш"""
        key = self._make_key(state)
        
        # LRU eviction если кэш полон
        if len(self.cache) >= self.max_size and key not in self.cache:
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]
            logger.debug(f"[RouteCache] Evicted oldest key {oldest_key[:8]}")
        
        self.cache[key] = route
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
        logger.debug(f"[RouteCache] Cached route {route} for key {key[:8]}")
    
    def clear(self):
        """Очистить кэш"""
        self.cache.clear()
        self.access_order.clear()
        logger.info("[RouteCache] Cache cleared")


class AgentPriorities:
    """Приоритеты агентов для оптимизации порядка выполнения"""
    
    # Приоритеты от высокого к низкому (меньше число = выше приоритет)
    PRIORITIES = {
        "document_classifier": 1,  # Самый высокий - должен запуститься первым
        "privilege_check": 2,      # Высокий - проверка привилегий важна
        "entity_extraction": 3,    # Средне-высокий - нужен для relationship
        "timeline": 4,             # Средний
        "key_facts": 4,            # Средний
        "discrepancy": 5,          # Средне-низкий - требует key_facts
        "relationship": 6,         # Низкий - требует entity_extraction
        "risk": 7,                 # Низкий - требует discrepancy
        "summary": 8,              # Самый низкий - требует key_facts
        "deep_analysis": 3,        # Средне-высокий - для сложных задач
    }
    
    @classmethod
    def get_priority(cls, agent_name: str) -> int:
        """Получить приоритет агента"""
        return cls.PRIORITIES.get(agent_name, 99)  # По умолчанию низкий приоритет
    
    @classmethod
    def sort_by_priority(cls, agent_names: List[str]) -> List[str]:
        """Отсортировать агентов по приоритету"""
        return sorted(agent_names, key=lambda x: cls.get_priority(x))


def optimize_route_function(
    base_route_func: Callable[[AnalysisState], Union[str, Any]],  # Can return str or Command
    enable_cache: bool = True,
    enable_priorities: bool = True
) -> Callable[[AnalysisState], Union[str, Any]]:
    """
    Обернуть функцию роутинга с оптимизациями (кэширование, приоритеты)
    
    Поддерживает как строки, так и Command для обратной совместимости.
    
    Args:
        base_route_func: Базовая функция роутинга (может возвращать str или Command)
        enable_cache: Включить кэширование решений
        enable_priorities: Использовать приоритеты агентов
        
    Returns:
        Оптимизированная функция роутинга (возвращает str или Command)
    """
    route_cache = RouteCache(max_size=100) if enable_cache else None
    
    def optimized_route(state: AnalysisState) -> Union[str, Any]:
        # Проверяем кэш (кэш работает со строками)
        if route_cache:
            cached_route = route_cache.get(state)
            if cached_route is not None:
                logger.debug(f"[OptimizedRoute] Using cached route: {cached_route}")
                # Если base_route_func использует Command, нужно вернуть Command
                # Но кэш хранит только строку, поэтому создаем Command если нужно
                # Проверим, использует ли base_route_func Command, вызвав его с use_command=False для проверки
                # Но это сложно, поэтому просто вернем строку - graph.py обработает и строку, и Command
                return cached_route
        
        # Вызываем базовую функцию роутинга
        # Check if function accepts use_command parameter
        # TEMPORARY FIX: Disable Command usage to avoid TypeError: unhashable type: 'dict'
        # LangGraph seems to have issues with Command objects in conditional edges
        import inspect
        sig = inspect.signature(base_route_func)
        if "use_command" in sig.parameters:
            route = base_route_func(state, use_command=False)  # Force False to disable Command
        else:
            route = base_route_func(state)
        
        # Сохраняем в кэш (извлекаем строку если это Command)
        if route_cache:
            route_str = route.goto if COMMAND_AVAILABLE and isinstance(route, Command) else route
            route_cache.set(state, route_str)
        
        # #region debug log
        if COMMAND_AVAILABLE and isinstance(route, Command):
            logger.info(f"[DEBUG] optimize_route returning Command: goto={route.goto}, update_type={type(route.update)}")
        else:
            logger.info(f"[DEBUG] optimize_route returning: {route}, type={type(route)}")
        # #endregion
        
        logger.debug(f"[OptimizedRoute] Computed route: {route}")
        return route
    
    return optimized_route


def get_next_agent_with_priorities(
    state: AnalysisState,
    available_agents: List[str],
    completed_agents: set,
    dependencies_ready: Dict[str, bool]
) -> Optional[str]:
    """
    Определить следующего агента с учетом приоритетов и зависимостей
    
    Args:
        state: Текущее состояние графа
        available_agents: Список доступных агентов
        completed_agents: Множество завершенных агентов
        dependencies_ready: Словарь готовности зависимостей
        
    Returns:
        Имя следующего агента или None
    """
    # Фильтруем агентов: только те, что не завершены и доступны
    pending_agents = [
        agent for agent in available_agents
        if agent not in completed_agents and agent in available_agents
    ]
    
    if not pending_agents:
        return None
    
    # Проверяем зависимости для каждого агента
    ready_agents = []
    for agent in pending_agents:
        # Проверяем зависимости агента
        if agent == "risk":
            if dependencies_ready.get("discrepancy", False):
                ready_agents.append(agent)
        elif agent == "summary":
            if dependencies_ready.get("key_facts", False):
                ready_agents.append(agent)
        elif agent == "relationship":
            if dependencies_ready.get("entity_extraction", False):
                ready_agents.append(agent)
        else:
            # Агенты без зависимостей всегда готовы
            ready_agents.append(agent)
    
    if not ready_agents:
        return None
    
    # Сортируем по приоритетам и возвращаем первого
    sorted_agents = AgentPriorities.sort_by_priority(ready_agents)
    return sorted_agents[0]


def create_optimized_conditional_edge(
    route_func: Callable[[AnalysisState], str],
    routes: Dict[str, str],
    enable_cache: bool = True,
    enable_priorities: bool = True
) -> Callable[[AnalysisState], str]:
    """
    Создать оптимизированную функцию для conditional edge
    
    Args:
        route_func: Функция роутинга
        routes: Словарь возможных маршрутов
        enable_cache: Включить кэширование
        enable_priorities: Использовать приоритеты
        
    Returns:
        Оптимизированная функция роутинга
    """
    return optimize_route_function(route_func, enable_cache, enable_priorities)

