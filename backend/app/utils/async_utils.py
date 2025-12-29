"""Утилиты для безопасного выполнения async кода из sync контекста"""
import asyncio
import logging
from typing import Any, Coroutine
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Глобальный executor для запуска async кода из потоков
_async_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="async_runner")


def run_async_safe(coro: Coroutine) -> Any:
    """
    Безопасно выполняет async корутину из sync контекста.
    
    Обрабатывает 3 случая:
    1. Event loop уже запущен (FastAPI) - использует executor для запуска в отдельном потоке
    2. Event loop существует, но не запущен - использует run_until_complete
    3. Event loop не существует - создает новый с asyncio.run
    
    Args:
        coro: Асинхронная корутина для выполнения
        
    Returns:
        Результат выполнения корутины
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Случай 1: Loop уже запущен (FastAPI async endpoint)
            # Используем executor для запуска в отдельном потоке
            logger.debug("Event loop is running, scheduling task in executor")
            future = _async_executor.submit(asyncio.run, coro)
            # Для синхронного ожидания результата используем executor
            return future.result(timeout=300)  # 5 минут timeout
        else:
            # Случай 2: Loop существует, но не запущен
            return loop.run_until_complete(coro)
    except RuntimeError:
        # Случай 3: Нет event loop
        return asyncio.run(coro)
    except Exception as e:
        logger.error(f"Error running async code: {e}", exc_info=True)
        raise

