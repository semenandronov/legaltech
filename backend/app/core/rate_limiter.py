"""
Rate Limiter - Ограничение частоты запросов

Предоставляет:
- Token Bucket алгоритм
- Per-user и per-endpoint лимиты
- Sliding window counter
- FastAPI middleware
"""
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps
import asyncio
import time
import logging

from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limit Exceeded Exception
# =============================================================================

class RateLimitExceeded(HTTPException):
    """Превышен лимит запросов"""
    def __init__(
        self,
        detail: str = "Rate limit exceeded",
        retry_after: Optional[int] = None
    ):
        headers = {}
        if retry_after:
            headers["Retry-After"] = str(retry_after)
        
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers=headers
        )


# =============================================================================
# Token Bucket Algorithm
# =============================================================================

@dataclass
class TokenBucket:
    """
    Token Bucket алгоритм для rate limiting
    
    Токены добавляются с фиксированной скоростью.
    Запрос потребляет токен. Если токенов нет - запрос отклоняется.
    
    Параметры:
    - capacity: максимальное количество токенов
    - refill_rate: токенов в секунду
    """
    capacity: int = 10
    refill_rate: float = 1.0  # токенов в секунду
    
    _tokens: float = field(default=None, init=False)
    _last_refill: float = field(default=None, init=False)
    
    def __post_init__(self):
        self._tokens = float(self.capacity)
        self._last_refill = time.time()
    
    def _refill(self) -> None:
        """Пополнить токены"""
        now = time.time()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self.refill_rate
        
        self._tokens = min(self.capacity, self._tokens + tokens_to_add)
        self._last_refill = now
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Попробовать потребить токены
        
        Returns:
            True если успешно, False если недостаточно токенов
        """
        self._refill()
        
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
    
    @property
    def available_tokens(self) -> float:
        """Доступные токены"""
        self._refill()
        return self._tokens
    
    @property
    def time_until_token(self) -> float:
        """Время до появления следующего токена (секунды)"""
        if self._tokens >= 1:
            return 0
        
        tokens_needed = 1 - self._tokens
        return tokens_needed / self.refill_rate


# =============================================================================
# Sliding Window Counter
# =============================================================================

@dataclass
class SlidingWindowCounter:
    """
    Sliding Window Counter для rate limiting
    
    Подсчитывает запросы в скользящем окне времени.
    Более точный чем fixed window, но требует больше памяти.
    
    Параметры:
    - window_size: размер окна в секундах
    - max_requests: максимум запросов в окне
    """
    window_size: int = 60  # секунды
    max_requests: int = 100
    
    _requests: list = field(default_factory=list, init=False)
    
    def _cleanup(self) -> None:
        """Удалить устаревшие запросы"""
        now = time.time()
        cutoff = now - self.window_size
        self._requests = [t for t in self._requests if t > cutoff]
    
    def record(self) -> bool:
        """
        Записать запрос
        
        Returns:
            True если запрос разрешён, False если лимит превышен
        """
        self._cleanup()
        
        if len(self._requests) >= self.max_requests:
            return False
        
        self._requests.append(time.time())
        return True
    
    @property
    def current_count(self) -> int:
        """Текущее количество запросов в окне"""
        self._cleanup()
        return len(self._requests)
    
    @property
    def remaining(self) -> int:
        """Оставшиеся запросы"""
        return max(0, self.max_requests - self.current_count)
    
    @property
    def reset_time(self) -> float:
        """Время до сброса окна (секунды)"""
        if not self._requests:
            return 0
        
        oldest = min(self._requests)
        return max(0, self.window_size - (time.time() - oldest))


# =============================================================================
# Rate Limiter Service
# =============================================================================

class RateLimiter:
    """
    Сервис rate limiting
    
    Поддерживает:
    - Per-user лимиты
    - Per-endpoint лимиты
    - Глобальные лимиты
    - Разные стратегии (token bucket, sliding window)
    """
    
    def __init__(self):
        # Per-user buckets
        self._user_buckets: Dict[str, TokenBucket] = {}
        
        # Per-endpoint counters
        self._endpoint_counters: Dict[str, SlidingWindowCounter] = {}
        
        # Global counter
        self._global_counter = SlidingWindowCounter(
            window_size=60,
            max_requests=1000
        )
        
        # Конфигурация по умолчанию
        self._default_user_config = {
            "capacity": 20,
            "refill_rate": 2.0
        }
        
        self._default_endpoint_config = {
            "window_size": 60,
            "max_requests": 100
        }
        
        # Кастомная конфигурация для эндпоинтов
        self._endpoint_configs: Dict[str, Dict] = {
            "/api/assistant/chat": {"window_size": 60, "max_requests": 30},
            "/api/v2/assistant/chat": {"window_size": 60, "max_requests": 30},
            "/api/upload": {"window_size": 60, "max_requests": 10},
        }
    
    def _get_user_bucket(self, user_id: str) -> TokenBucket:
        """Получить или создать bucket для пользователя"""
        if user_id not in self._user_buckets:
            self._user_buckets[user_id] = TokenBucket(
                **self._default_user_config
            )
        return self._user_buckets[user_id]
    
    def _get_endpoint_counter(self, endpoint: str) -> SlidingWindowCounter:
        """Получить или создать counter для эндпоинта"""
        if endpoint not in self._endpoint_counters:
            config = self._endpoint_configs.get(
                endpoint,
                self._default_endpoint_config
            )
            self._endpoint_counters[endpoint] = SlidingWindowCounter(**config)
        return self._endpoint_counters[endpoint]
    
    def check_rate_limit(
        self,
        user_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        tokens: int = 1
    ) -> tuple[bool, Dict[str, Any]]:
        """
        Проверить rate limit
        
        Args:
            user_id: ID пользователя (опционально)
            endpoint: Путь эндпоинта (опционально)
            tokens: Количество токенов для потребления
            
        Returns:
            (allowed, info) - разрешён ли запрос и информация о лимитах
        """
        info = {
            "user_allowed": True,
            "endpoint_allowed": True,
            "global_allowed": True,
        }
        
        # Проверяем глобальный лимит
        if not self._global_counter.record():
            info["global_allowed"] = False
            info["retry_after"] = int(self._global_counter.reset_time)
            return False, info
        
        # Проверяем per-user лимит
        if user_id:
            bucket = self._get_user_bucket(user_id)
            if not bucket.consume(tokens):
                info["user_allowed"] = False
                info["retry_after"] = int(bucket.time_until_token) + 1
                info["user_remaining"] = bucket.available_tokens
                return False, info
            info["user_remaining"] = bucket.available_tokens
        
        # Проверяем per-endpoint лимит
        if endpoint:
            counter = self._get_endpoint_counter(endpoint)
            if not counter.record():
                info["endpoint_allowed"] = False
                info["retry_after"] = int(counter.reset_time)
                info["endpoint_remaining"] = counter.remaining
                return False, info
            info["endpoint_remaining"] = counter.remaining
        
        return True, info
    
    def get_status(self) -> Dict[str, Any]:
        """Получить статус rate limiter"""
        return {
            "global": {
                "current": self._global_counter.current_count,
                "max": self._global_counter.max_requests,
                "remaining": self._global_counter.remaining
            },
            "users_tracked": len(self._user_buckets),
            "endpoints_tracked": len(self._endpoint_counters)
        }


# =============================================================================
# Global Rate Limiter Instance
# =============================================================================

_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Получить глобальный rate limiter"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


# =============================================================================
# FastAPI Middleware
# =============================================================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware для rate limiting
    
    Пример использования:
    ```python
    app.add_middleware(RateLimitMiddleware)
    ```
    """
    
    # Эндпоинты без rate limiting
    EXCLUDED_PATHS = {
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
    
    async def dispatch(self, request: Request, call_next):
        # Пропускаем исключённые пути
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)
        
        # Получаем user_id из request state (если есть)
        user_id = None
        if hasattr(request.state, "user") and request.state.user:
            user_id = getattr(request.state.user, "id", None)
        
        # Проверяем rate limit
        limiter = get_rate_limiter()
        allowed, info = limiter.check_rate_limit(
            user_id=user_id,
            endpoint=request.url.path
        )
        
        if not allowed:
            retry_after = info.get("retry_after", 60)
            logger.warning(
                f"Rate limit exceeded: user={user_id}, endpoint={request.url.path}"
            )
            raise RateLimitExceeded(
                detail="Too many requests. Please try again later.",
                retry_after=retry_after
            )
        
        # Добавляем заголовки с информацией о лимитах
        response = await call_next(request)
        
        if "user_remaining" in info:
            response.headers["X-RateLimit-Remaining"] = str(int(info["user_remaining"]))
        if "endpoint_remaining" in info:
            response.headers["X-RateLimit-Endpoint-Remaining"] = str(info["endpoint_remaining"])
        
        return response


# =============================================================================
# Decorator для rate limiting
# =============================================================================

def rate_limit(
    max_requests: int = 10,
    window_seconds: int = 60,
    key_func: Optional[Callable[[Request], str]] = None
):
    """
    Декоратор для rate limiting на уровне endpoint
    
    Пример:
    ```python
    @router.post("/api/chat")
    @rate_limit(max_requests=30, window_seconds=60)
    async def chat(request: Request):
        ...
    ```
    """
    counters: Dict[str, SlidingWindowCounter] = {}
    
    def get_key(request: Request) -> str:
        if key_func:
            return key_func(request)
        
        # По умолчанию используем IP + user_id
        client_ip = request.client.host if request.client else "unknown"
        user_id = ""
        if hasattr(request.state, "user") and request.state.user:
            user_id = getattr(request.state.user, "id", "")
        
        return f"{client_ip}:{user_id}"
    
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            key = get_key(request)
            
            if key not in counters:
                counters[key] = SlidingWindowCounter(
                    window_size=window_seconds,
                    max_requests=max_requests
                )
            
            counter = counters[key]
            
            if not counter.record():
                raise RateLimitExceeded(
                    detail=f"Rate limit exceeded. Max {max_requests} requests per {window_seconds}s.",
                    retry_after=int(counter.reset_time) + 1
                )
            
            return await func(request, *args, **kwargs)
        
        return wrapper
    return decorator

