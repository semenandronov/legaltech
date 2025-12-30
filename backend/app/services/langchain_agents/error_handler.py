"""Error handling and retry mechanisms for LangGraph nodes"""
from typing import Dict, Any, Optional, Callable, Type, Tuple
from app.services.langchain_agents.state import AnalysisState
from functools import wraps
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class RetryConfig:
    """Конфигурация retry механизма"""
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,)
    ):
        """
        Args:
            max_retries: Максимальное количество попыток
            initial_delay: Начальная задержка в секундах
            max_delay: Максимальная задержка в секундах
            exponential_base: База экспоненциального backoff
            retryable_exceptions: Типы исключений, которые можно повторить
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_exceptions = retryable_exceptions


class NodeErrorHandler:
    """Обработчик ошибок для узлов графа"""
    
    @staticmethod
    def should_retry(error: Exception, retry_config: RetryConfig, attempt: int) -> bool:
        """
        Определить, нужно ли повторить выполнение после ошибки
        
        Args:
            error: Произошедшая ошибка
            retry_config: Конфигурация retry
            attempt: Номер текущей попытки
        
        Returns:
            True если нужно повторить
        """
        if attempt >= retry_config.max_retries:
            return False
        
        # Проверяем тип исключения
        if not isinstance(error, retry_config.retryable_exceptions):
            return False
        
        # Некоторые ошибки не стоит повторять
        error_str = str(error).lower()
        non_retryable_keywords = [
            "validation",
            "syntax",
            "not found",
            "permission denied",
            "authentication",
            "authorization"
        ]
        
        if any(keyword in error_str for keyword in non_retryable_keywords):
            logger.debug(f"[ErrorHandler] Non-retryable error: {error_str}")
            return False
        
        return True
    
    @staticmethod
    def calculate_delay(retry_config: RetryConfig, attempt: int) -> float:
        """
        Вычислить задержку перед следующей попыткой (exponential backoff)
        
        Args:
            retry_config: Конфигурация retry
            attempt: Номер текущей попытки
        
        Returns:
            Задержка в секундах
        """
        delay = retry_config.initial_delay * (retry_config.exponential_base ** attempt)
        return min(delay, retry_config.max_delay)
    
    @staticmethod
    def handle_error(
        state: AnalysisState,
        node_name: str,
        error: Exception,
        attempt: int,
        retry_config: RetryConfig
    ) -> AnalysisState:
        """
        Обработать ошибку узла и обновить состояние
        
        Args:
            state: Текущее состояние графа
            node_name: Имя узла, в котором произошла ошибка
            error: Произошедшая ошибка
            attempt: Номер текущей попытки
            retry_config: Конфигурация retry
        
        Returns:
            Обновленное состояние с информацией об ошибке
        """
        new_state = dict(state)
        
        # Инициализируем метаданные если их нет
        if "metadata" not in new_state:
            new_state["metadata"] = {}
        if "errors" not in new_state["metadata"]:
            new_state["metadata"]["errors"] = {}
        if node_name not in new_state["metadata"]["errors"]:
            new_state["metadata"]["errors"][node_name] = []
        
        # Записываем информацию об ошибке
        error_info = {
            "attempt": attempt,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp": datetime.now().isoformat(),
            "will_retry": NodeErrorHandler.should_retry(error, retry_config, attempt)
        }
        
        new_state["metadata"]["errors"][node_name].append(error_info)
        
        # Ограничиваем количество сохраненных ошибок
        if len(new_state["metadata"]["errors"][node_name]) > 10:
            new_state["metadata"]["errors"][node_name] = new_state["metadata"]["errors"][node_name][-10:]
        
        logger.warning(
            f"[ErrorHandler] Node {node_name} error (attempt {attempt}/{retry_config.max_retries}): "
            f"{type(error).__name__}: {str(error)}"
        )
        
        return new_state


def with_retry(
    retry_config: Optional[RetryConfig] = None,
    node_name: Optional[str] = None
):
    """
    Декоратор для узлов графа с поддержкой retry механизма
    
    Args:
        retry_config: Конфигурация retry (по умолчанию используется стандартная)
        node_name: Имя узла (если не указано, берется из функции)
    
    Usage:
        @with_retry(retry_config=RetryConfig(max_retries=5))
        def my_node(state: AnalysisState) -> AnalysisState:
            # ... node implementation
    """
    if retry_config is None:
        retry_config = RetryConfig()
    
    def decorator(node_func: Callable[[AnalysisState], AnalysisState]):
        _node_name = node_name or node_func.__name__
        
        @wraps(node_func)
        def wrapped_node(state: AnalysisState) -> AnalysisState:
            last_error = None
            
            for attempt in range(retry_config.max_retries):
                try:
                    # Выполняем узел
                    result_state = node_func(state)
                    
                    # Если выполнение успешно, очищаем ошибки в метаданных
                    if attempt > 0:
                        logger.info(
                            f"[ErrorHandler] Node {_node_name} succeeded after {attempt} retries"
                        )
                        if "metadata" in result_state and "errors" in result_state["metadata"]:
                            result_state["metadata"]["errors"].pop(_node_name, None)
                    
                    return result_state
                    
                except Exception as e:
                    last_error = e
                    
                    # Обрабатываем ошибку
                    state = NodeErrorHandler.handle_error(state, _node_name, e, attempt + 1, retry_config)
                    
                    # Проверяем, нужно ли повторить
                    if not NodeErrorHandler.should_retry(e, retry_config, attempt + 1):
                        logger.error(
                            f"[ErrorHandler] Node {_node_name} failed after {attempt + 1} attempts, "
                            f"not retrying: {type(e).__name__}: {str(e)}"
                        )
                        raise
                    
                    # Вычисляем задержку и ждем
                    delay = NodeErrorHandler.calculate_delay(retry_config, attempt)
                    logger.info(
                        f"[ErrorHandler] Retrying node {_node_name} after {delay:.2f}s "
                        f"(attempt {attempt + 2}/{retry_config.max_retries})"
                    )
                    time.sleep(delay)
            
            # Все попытки исчерпаны
            logger.error(
                f"[ErrorHandler] Node {_node_name} failed after {retry_config.max_retries} attempts"
            )
            raise last_error
        
        wrapped_node.__name__ = node_func.__name__
        wrapped_node.__doc__ = node_func.__doc__
        return wrapped_node
    
    return decorator


def with_error_recovery(
    fallback_state: Optional[Callable[[AnalysisState, Exception], AnalysisState]] = None
):
    """
    Декоратор для узлов графа с поддержкой recovery после ошибок
    
    Args:
        fallback_state: Функция для создания fallback состояния при ошибке
    
    Usage:
        def create_fallback_state(state: AnalysisState, error: Exception) -> AnalysisState:
            new_state = dict(state)
            new_state["error_recovered"] = True
            return new_state
        
        @with_error_recovery(fallback_state=create_fallback_state)
        def my_node(state: AnalysisState) -> AnalysisState:
            # ... node implementation
    """
    def decorator(node_func: Callable[[AnalysisState], AnalysisState]):
        @wraps(node_func)
        def wrapped_node(state: AnalysisState) -> AnalysisState:
            try:
                return node_func(state)
            except Exception as e:
                logger.error(
                    f"[ErrorRecovery] Error in node {node_func.__name__}: {type(e).__name__}: {str(e)}"
                )
                
                if fallback_state:
                    try:
                        recovered_state = fallback_state(state, e)
                        logger.info(
                            f"[ErrorRecovery] Successfully recovered from error in node {node_func.__name__}"
                        )
                        return recovered_state
                    except Exception as recovery_error:
                        logger.error(
                            f"[ErrorRecovery] Failed to recover from error: {type(recovery_error).__name__}: {str(recovery_error)}"
                        )
                
                # Re-raise if no recovery possible
                raise
        
        wrapped_node.__name__ = node_func.__name__
        wrapped_node.__doc__ = node_func.__doc__
        return wrapped_node
    
    return decorator

