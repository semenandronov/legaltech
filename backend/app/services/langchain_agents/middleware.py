"""Middleware system for LangGraph nodes"""
from typing import Dict, Any, Callable, Optional
from app.services.langchain_agents.state import AnalysisState
import logging
from functools import wraps

logger = logging.getLogger(__name__)


class NodeMiddleware:
    """Базовый класс для middleware узлов графа"""
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        """
        Вызывается перед выполнением узла
        
        Args:
            state: Текущее состояние
            node_name: Имя узла
        
        Returns:
            Обновленное состояние
        """
        return state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        """
        Вызывается после выполнения узла
        
        Args:
            state: Исходное состояние
            node_name: Имя узла
            result_state: Результирующее состояние
        
        Returns:
            Обновленное состояние
        """
        return result_state
    
    def on_error(self, state: AnalysisState, node_name: str, error: Exception) -> Optional[AnalysisState]:
        """
        Вызывается при ошибке в узле
        
        Args:
            state: Состояние на момент ошибки
            node_name: Имя узла
            error: Произошедшая ошибка
        
        Returns:
            Состояние для восстановления или None
        """
        return None


class LoggingMiddleware(NodeMiddleware):
    """Middleware для логирования выполнения узлов"""
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        case_id = state.get("case_id", "unknown")
        logger.info(f"[Middleware:Logging] Before {node_name} execution for case {case_id}")
        return state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        case_id = result_state.get("case_id", "unknown")
        logger.info(f"[Middleware:Logging] After {node_name} execution for case {case_id}")
        return result_state
    
    def on_error(self, state: AnalysisState, node_name: str, error: Exception) -> Optional[AnalysisState]:
        case_id = state.get("case_id", "unknown")
        logger.error(f"[Middleware:Logging] Error in {node_name} for case {case_id}: {error}", exc_info=True)
        return None


class MonitoringMiddleware(NodeMiddleware):
    """Middleware для мониторинга производительности"""
    
    def __init__(self):
        from app.services.langchain_agents.graph_monitoring import get_graph_monitor
        self.monitor = get_graph_monitor()
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        case_id = state.get("case_id", "unknown")
        self.monitor.start_node_execution(case_id, node_name)
        return state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        case_id = result_state.get("case_id", "unknown")
        self.monitor.end_node_execution(case_id, node_name)
        return result_state


class CachingMiddleware(NodeMiddleware):
    """Middleware для кэширования результатов узлов"""
    
    def __init__(self, cache_size: int = 100):
        self.cache: Dict[str, AnalysisState] = {}
        self.cache_size = cache_size
    
    def _make_cache_key(self, state: AnalysisState, node_name: str) -> str:
        """Создать ключ кэша"""
        import hashlib
        import json
        
        # Используем релевантные поля состояния для ключа
        key_data = {
            "node_name": node_name,
            "case_id": state.get("case_id"),
            "analysis_types": state.get("analysis_types", []),
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        cache_key = self._make_cache_key(state, node_name)
        
        if cache_key in self.cache:
            logger.debug(f"[Middleware:Caching] Cache hit for {node_name}")
            # Возвращаем закэшированное состояние
            cached_state = self.cache[cache_key]
            # Но продолжаем выполнение, кэш используется только для информации
            return state
        
        return state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        cache_key = self._make_cache_key(state, node_name)
        
        # LRU eviction
        if len(self.cache) >= self.cache_size:
            # Удаляем первый элемент (простейшая LRU)
            first_key = next(iter(self.cache))
            del self.cache[first_key]
        
        self.cache[cache_key] = result_state
        logger.debug(f"[Middleware:Caching] Cached result for {node_name}")
        
        return result_state


class MiddlewareChain:
    """Цепочка middleware для последовательного выполнения"""
    
    def __init__(self, middlewares: Optional[List[NodeMiddleware]] = None):
        self.middlewares = middlewares or []
    
    def add(self, middleware: NodeMiddleware):
        """Добавить middleware в цепочку"""
        self.middlewares.append(middleware)
        logger.debug(f"Added middleware {type(middleware).__name__} to chain")
    
    def execute(
        self,
        node_func: Callable[[AnalysisState], AnalysisState],
        state: AnalysisState,
        node_name: str
    ) -> AnalysisState:
        """
        Выполнить узел с применением всех middleware
        
        Args:
            node_func: Функция узла
            state: Исходное состояние
            node_name: Имя узла
        
        Returns:
            Результирующее состояние
        """
        # Before execution
        current_state = state
        for middleware in self.middlewares:
            current_state = middleware.before_execution(current_state, node_name)
        
        # Execute node
        try:
            result_state = node_func(current_state)
        except Exception as e:
            # On error
            for middleware in reversed(self.middlewares):
                recovered_state = middleware.on_error(current_state, node_name, e)
                if recovered_state is not None:
                    logger.info(f"[Middleware] Recovered from error using {type(middleware).__name__}")
                    result_state = recovered_state
                    break
            else:
                # No middleware handled the error, re-raise
                raise
        
        # After execution
        final_state = result_state
        for middleware in reversed(self.middlewares):
            final_state = middleware.after_execution(state, node_name, final_state)
        
        return final_state


def with_middleware(
    middlewares: List[NodeMiddleware],
    node_name: Optional[str] = None
):
    """
    Декоратор для применения middleware к узлу
    
    Args:
        middlewares: Список middleware для применения
        node_name: Имя узла (если не указано, берется из функции)
    
    Usage:
        @with_middleware([LoggingMiddleware(), MonitoringMiddleware()])
        def my_node(state: AnalysisState) -> AnalysisState:
            # ... node implementation
    """
    def decorator(node_func: Callable[[AnalysisState], AnalysisState]):
        _node_name = node_name or node_func.__name__
        chain = MiddlewareChain(middlewares)
        
        @wraps(node_func)
        def wrapped_node(state: AnalysisState) -> AnalysisState:
            return chain.execute(node_func, state, _node_name)
        
        wrapped_node.__name__ = node_func.__name__
        wrapped_node.__doc__ = node_func.__doc__
        return wrapped_node
    
    return decorator

