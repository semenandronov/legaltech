"""
Resilience Module - Устойчивость к сбоям

Предоставляет:
- Retry с exponential backoff
- Circuit Breaker для внешних сервисов
- Timeout wrapper
- Fallback механизмы
"""
from typing import TypeVar, Callable, Optional, Any, Dict, List
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

T = TypeVar('T')


# =============================================================================
# Retry с Exponential Backoff
# =============================================================================

class RetryError(Exception):
    """Ошибка после исчерпания попыток"""
    def __init__(self, message: str, last_exception: Optional[Exception] = None):
        super().__init__(message)
        self.last_exception = last_exception


@dataclass
class RetryConfig:
    """Конфигурация retry"""
    max_attempts: int = 3
    initial_delay: float = 1.0  # секунды
    max_delay: float = 30.0  # секунды
    exponential_base: float = 2.0
    jitter: bool = True  # Добавлять случайный jitter
    retryable_exceptions: tuple = (Exception,)
    non_retryable_exceptions: tuple = ()


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Вычислить задержку для попытки"""
    delay = config.initial_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)
    
    if config.jitter:
        import random
        delay = delay * (0.5 + random.random())
    
    return delay


def retry(config: Optional[RetryConfig] = None):
    """
    Декоратор для retry с exponential backoff
    
    Пример:
    ```python
    @retry(RetryConfig(max_attempts=3))
    async def call_external_api():
        ...
    ```
    """
    if config is None:
        config = RetryConfig()
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                    
                except config.non_retryable_exceptions as e:
                    logger.warning(f"Non-retryable error in {func.__name__}: {e}")
                    raise
                    
                except config.retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts - 1:
                        delay = calculate_delay(attempt, config)
                        logger.warning(
                            f"Attempt {attempt + 1}/{config.max_attempts} failed for {func.__name__}: {e}. "
                            f"Retrying in {delay:.2f}s…"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_attempts} attempts failed for {func.__name__}: {e}"
                        )
            
            raise RetryError(
                f"Failed after {config.max_attempts} attempts",
                last_exception
            )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(config.max_attempts):
                try:
                    return func(*args, **kwargs)
                    
                except config.non_retryable_exceptions as e:
                    raise
                    
                except config.retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < config.max_attempts - 1:
                        delay = calculate_delay(attempt, config)
                        logger.warning(
                            f"Attempt {attempt + 1}/{config.max_attempts} failed: {e}. "
                            f"Retrying in {delay:.2f}s…"
                        )
                        time.sleep(delay)
            
            raise RetryError(
                f"Failed after {config.max_attempts} attempts",
                last_exception
            )
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================================================
# Circuit Breaker
# =============================================================================

class CircuitState(Enum):
    """Состояние Circuit Breaker"""
    CLOSED = "closed"      # Нормальная работа
    OPEN = "open"          # Сервис недоступен, запросы блокируются
    HALF_OPEN = "half_open"  # Пробуем восстановить


class CircuitBreakerError(Exception):
    """Ошибка Circuit Breaker (сервис недоступен)"""
    pass


@dataclass
class CircuitBreakerConfig:
    """Конфигурация Circuit Breaker"""
    failure_threshold: int = 5  # Порог ошибок для открытия
    success_threshold: int = 2  # Порог успехов для закрытия
    timeout: float = 30.0  # Время в OPEN состоянии (секунды)
    half_open_max_calls: int = 3  # Макс. вызовов в HALF_OPEN


@dataclass
class CircuitBreaker:
    """
    Circuit Breaker для защиты от каскадных сбоев
    
    Состояния:
    - CLOSED: нормальная работа, считаем ошибки
    - OPEN: сервис недоступен, все запросы отклоняются
    - HALF_OPEN: пробуем восстановить, ограниченное число запросов
    
    Пример:
    ```python
    cb = CircuitBreaker("external_api")
    
    async def call_api():
        async with cb:
            return await external_api.call()
    ```
    """
    name: str
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    
    # Internal state
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _success_count: int = field(default=0, init=False)
    _last_failure_time: Optional[datetime] = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    
    @property
    def state(self) -> CircuitState:
        """Текущее состояние"""
        self._check_state_transition()
        return self._state
    
    def _check_state_transition(self) -> None:
        """Проверить и выполнить переход состояния"""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time:
                elapsed = (datetime.utcnow() - self._last_failure_time).total_seconds()
                if elapsed >= self.config.timeout:
                    logger.info(f"Circuit {self.name}: OPEN → HALF_OPEN (timeout expired)")
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
    
    def _record_success(self) -> None:
        """Записать успешный вызов"""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                logger.info(f"Circuit {self.name}: HALF_OPEN → CLOSED (success threshold reached)")
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        elif self._state == CircuitState.CLOSED:
            # Сбрасываем счётчик ошибок при успехе
            self._failure_count = max(0, self._failure_count - 1)
    
    def _record_failure(self) -> None:
        """Записать неудачный вызов"""
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()
        
        if self._state == CircuitState.CLOSED:
            if self._failure_count >= self.config.failure_threshold:
                logger.warning(f"Circuit {self.name}: CLOSED → OPEN (failure threshold reached)")
                self._state = CircuitState.OPEN
        elif self._state == CircuitState.HALF_OPEN:
            logger.warning(f"Circuit {self.name}: HALF_OPEN → OPEN (failure in half-open)")
            self._state = CircuitState.OPEN
    
    def can_execute(self) -> bool:
        """Можно ли выполнить запрос"""
        state = self.state  # Triggers state check
        
        if state == CircuitState.CLOSED:
            return True
        elif state == CircuitState.OPEN:
            return False
        elif state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.config.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        
        return False
    
    async def __aenter__(self):
        """Async context manager entry"""
        if not self.can_execute():
            raise CircuitBreakerError(
                f"Circuit {self.name} is OPEN. Service unavailable."
            )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if exc_type is None:
            self._record_success()
        else:
            self._record_failure()
        return False  # Don't suppress exception
    
    def __enter__(self):
        """Sync context manager entry"""
        if not self.can_execute():
            raise CircuitBreakerError(
                f"Circuit {self.name} is OPEN. Service unavailable."
            )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit"""
        if exc_type is None:
            self._record_success()
        else:
            self._record_failure()
        return False
    
    def reset(self) -> None:
        """Сбросить состояние"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0
        logger.info(f"Circuit {self.name}: RESET → CLOSED")


# =============================================================================
# Circuit Breaker Registry
# =============================================================================

class CircuitBreakerRegistry:
    """Реестр Circuit Breaker'ов"""
    
    _breakers: Dict[str, CircuitBreaker] = {}
    
    @classmethod
    def get(cls, name: str, config: Optional[CircuitBreakerConfig] = None) -> CircuitBreaker:
        """Получить или создать Circuit Breaker"""
        if name not in cls._breakers:
            cls._breakers[name] = CircuitBreaker(
                name=name,
                config=config or CircuitBreakerConfig()
            )
        return cls._breakers[name]
    
    @classmethod
    def reset_all(cls) -> None:
        """Сбросить все Circuit Breaker'ы"""
        for breaker in cls._breakers.values():
            breaker.reset()
    
    @classmethod
    def get_status(cls) -> Dict[str, Dict[str, Any]]:
        """Получить статус всех Circuit Breaker'ов"""
        return {
            name: {
                "state": breaker.state.value,
                "failure_count": breaker._failure_count,
                "success_count": breaker._success_count,
                "last_failure": breaker._last_failure_time.isoformat() if breaker._last_failure_time else None
            }
            for name, breaker in cls._breakers.items()
        }


# =============================================================================
# Timeout Wrapper
# =============================================================================

class TimeoutError(Exception):
    """Ошибка таймаута"""
    pass


def with_timeout(seconds: float):
    """
    Декоратор для добавления таймаута к async функции
    
    Пример:
    ```python
    @with_timeout(30.0)
    async def slow_operation():
        ...
    ```
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=seconds
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Operation {func.__name__} timed out after {seconds}s"
                )
        return wrapper
    return decorator


# =============================================================================
# Fallback Wrapper
# =============================================================================

def with_fallback(fallback_func: Callable[..., T]):
    """
    Декоратор для добавления fallback при ошибке
    
    Пример:
    ```python
    def fallback_response():
        return {"status": "degraded", "data": []}
    
    @with_fallback(fallback_response)
    async def get_data():
        ...
    ```
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Function {func.__name__} failed: {e}. Using fallback."
                )
                if asyncio.iscoroutinefunction(fallback_func):
                    return await fallback_func(*args, **kwargs)
                return fallback_func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(
                    f"Function {func.__name__} failed: {e}. Using fallback."
                )
                return fallback_func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================================================
# Bulkhead (Concurrency Limiter)
# =============================================================================

class Bulkhead:
    """
    Bulkhead pattern для ограничения параллельных вызовов
    
    Предотвращает перегрузку сервиса слишком большим количеством
    одновременных запросов.
    
    Пример:
    ```python
    bulkhead = Bulkhead("llm_calls", max_concurrent=5)
    
    async def call_llm():
        async with bulkhead:
            return await llm.invoke(...)
    ```
    """
    
    def __init__(self, name: str, max_concurrent: int = 10):
        self.name = name
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._current = 0
    
    @property
    def current_calls(self) -> int:
        """Текущее количество активных вызовов"""
        return self._current
    
    @property
    def available_slots(self) -> int:
        """Доступные слоты"""
        return self.max_concurrent - self._current
    
    async def __aenter__(self):
        await self._semaphore.acquire()
        self._current += 1
        logger.debug(f"Bulkhead {self.name}: acquired ({self._current}/{self.max_concurrent})")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._current -= 1
        self._semaphore.release()
        logger.debug(f"Bulkhead {self.name}: released ({self._current}/{self.max_concurrent})")
        return False


# =============================================================================
# Предустановленные конфигурации
# =============================================================================

# Для LLM вызовов
LLM_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=2.0,
    max_delay=30.0,
    retryable_exceptions=(ConnectionError, TimeoutError, Exception),
    non_retryable_exceptions=(ValueError, TypeError)
)

# Для внешних API (ГАРАНТ, веб-поиск)
EXTERNAL_API_RETRY_CONFIG = RetryConfig(
    max_attempts=2,
    initial_delay=1.0,
    max_delay=10.0,
)

# Для базы данных
DB_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=0.5,
    max_delay=5.0,
)

# Circuit Breaker для LLM
LLM_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0
)

# Circuit Breaker для внешних API
EXTERNAL_API_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=3,
    success_threshold=1,
    timeout=30.0
)

