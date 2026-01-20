"""
Structured Logging - Структурированное логирование

Предоставляет:
- Correlation IDs для трейсинга запросов
- Structured JSON logging
- Request/Response logging
- Performance logging
"""
from typing import Optional, Dict, Any
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
import logging
import json
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# =============================================================================
# Context Variables для Correlation ID
# =============================================================================

correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
request_context_var: ContextVar[Optional[Dict[str, Any]]] = ContextVar('request_context', default=None)


def get_correlation_id() -> Optional[str]:
    """Получить текущий correlation ID"""
    return correlation_id_var.get()


def set_correlation_id(correlation_id: str) -> None:
    """Установить correlation ID"""
    correlation_id_var.set(correlation_id)


def get_request_context() -> Optional[Dict[str, Any]]:
    """Получить контекст запроса"""
    return request_context_var.get()


def set_request_context(context: Dict[str, Any]) -> None:
    """Установить контекст запроса"""
    request_context_var.set(context)


# =============================================================================
# Structured Log Formatter
# =============================================================================

class StructuredFormatter(logging.Formatter):
    """
    Форматтер для структурированного JSON логирования
    """
    
    def format(self, record: logging.LogRecord) -> str:
        # Базовые поля
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Добавляем correlation ID если есть
        correlation_id = get_correlation_id()
        if correlation_id:
            log_data["correlation_id"] = correlation_id
        
        # Добавляем контекст запроса если есть
        request_context = get_request_context()
        if request_context:
            log_data["request"] = request_context
        
        # Добавляем extra поля
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)
        
        # Добавляем exception если есть
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False, default=str)


class HumanReadableFormatter(logging.Formatter):
    """
    Форматтер для человекочитаемого вывода (development)
    """
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, '')
        
        # Формируем timestamp
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        
        # Добавляем correlation ID если есть
        correlation_id = get_correlation_id()
        corr_str = f"[{correlation_id[:8]}] " if correlation_id else ""
        
        # Формируем сообщение
        message = record.getMessage()
        
        # Базовый формат
        formatted = f"{color}{timestamp} | {record.levelname:8} | {corr_str}{record.name}:{record.lineno} | {message}{self.RESET}"
        
        # Добавляем exception если есть
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        
        return formatted


# =============================================================================
# Logger с дополнительным контекстом
# =============================================================================

class ContextLogger(logging.LoggerAdapter):
    """
    Logger adapter с автоматическим добавлением контекста
    """
    
    def process(self, msg, kwargs):
        extra = kwargs.get('extra', {})
        
        # Добавляем correlation ID
        correlation_id = get_correlation_id()
        if correlation_id:
            extra['correlation_id'] = correlation_id
        
        # Добавляем контекст запроса
        request_context = get_request_context()
        if request_context:
            extra['request_context'] = request_context
        
        kwargs['extra'] = extra
        return msg, kwargs


def get_logger(name: str) -> ContextLogger:
    """Получить logger с контекстом"""
    logger = logging.getLogger(name)
    return ContextLogger(logger, {})


# =============================================================================
# Middleware для логирования запросов
# =============================================================================

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования HTTP запросов
    
    - Генерирует correlation ID
    - Логирует request/response
    - Измеряет время выполнения
    """
    
    # Пути без детального логирования
    SKIP_PATHS = {
        "/api/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
    }
    
    async def dispatch(self, request: Request, call_next):
        # Пропускаем некоторые пути
        if request.url.path in self.SKIP_PATHS:
            return await call_next(request)
        
        # Генерируем или извлекаем correlation ID
        correlation_id = request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        set_correlation_id(correlation_id)
        
        # Устанавливаем контекст запроса
        request_context = {
            "method": request.method,
            "path": request.url.path,
            "query": str(request.query_params) if request.query_params else None,
            "client_ip": request.client.host if request.client else None,
        }
        set_request_context(request_context)
        
        # Логируем начало запроса
        logger = get_logger("http")
        logger.info(f"→ {request.method} {request.url.path}")
        
        # Измеряем время
        start_time = time.time()
        
        try:
            response = await call_next(request)
            
            # Вычисляем время
            duration_ms = (time.time() - start_time) * 1000
            
            # Логируем ответ
            logger.info(
                f"← {request.method} {request.url.path} | {response.status_code} | {duration_ms:.2f}ms"
            )
            
            # Добавляем заголовки
            response.headers["X-Correlation-ID"] = correlation_id
            response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
            
            return response
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"✗ {request.method} {request.url.path} | ERROR | {duration_ms:.2f}ms | {str(e)}"
            )
            raise
        finally:
            # Очищаем контекст
            correlation_id_var.set(None)
            request_context_var.set(None)


# =============================================================================
# Performance Logging Decorator
# =============================================================================

def log_performance(name: Optional[str] = None, threshold_ms: float = 1000):
    """
    Декоратор для логирования производительности функции
    
    Args:
        name: Имя для логов (по умолчанию имя функции)
        threshold_ms: Порог для warning (миллисекунды)
    
    Пример:
    ```python
    @log_performance(threshold_ms=500)
    async def slow_operation():
        ...
    ```
    """
    def decorator(func):
        func_name = name or func.__name__
        logger = get_logger(f"perf.{func_name}")
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                
                if duration_ms > threshold_ms:
                    logger.warning(f"{func_name} took {duration_ms:.2f}ms (threshold: {threshold_ms}ms)")
                else:
                    logger.debug(f"{func_name} completed in {duration_ms:.2f}ms")
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                logger.error(f"{func_name} failed after {duration_ms:.2f}ms: {e}")
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000
                
                if duration_ms > threshold_ms:
                    logger.warning(f"{func_name} took {duration_ms:.2f}ms (threshold: {threshold_ms}ms)")
                else:
                    logger.debug(f"{func_name} completed in {duration_ms:.2f}ms")
                
                return result
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                logger.error(f"{func_name} failed after {duration_ms:.2f}ms: {e}")
                raise
        
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator


# =============================================================================
# Setup Logging
# =============================================================================

def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None
):
    """
    Настроить логирование приложения
    
    Args:
        level: Уровень логирования
        json_format: Использовать JSON формат (для production)
        log_file: Путь к файлу логов (опционально)
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Удаляем существующие handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Выбираем форматтер
    if json_format:
        formatter = StructuredFormatter()
    else:
        formatter = HumanReadableFormatter()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (если указан)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(StructuredFormatter())  # Файл всегда в JSON
        root_logger.addHandler(file_handler)
    
    # Уменьшаем verbosity некоторых библиотек
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    
    logger = get_logger(__name__)
    logger.info(f"Logging configured: level={level}, json={json_format}")

