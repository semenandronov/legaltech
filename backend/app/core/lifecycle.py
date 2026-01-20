"""
Application Lifecycle - Управление жизненным циклом приложения

Предоставляет:
- Graceful shutdown
- Startup/shutdown hooks
- Resource cleanup
"""
from typing import Callable, List, Optional
from contextlib import asynccontextmanager
import asyncio
import signal
import logging

logger = logging.getLogger(__name__)


class LifecycleManager:
    """
    Менеджер жизненного цикла приложения
    
    Управляет:
    - Startup hooks
    - Shutdown hooks
    - Graceful shutdown с таймаутом
    """
    
    def __init__(self, shutdown_timeout: float = 30.0):
        """
        Инициализация менеджера
        
        Args:
            shutdown_timeout: Таймаут для graceful shutdown (секунды)
        """
        self.shutdown_timeout = shutdown_timeout
        self._startup_hooks: List[Callable] = []
        self._shutdown_hooks: List[Callable] = []
        self._is_shutting_down = False
        self._shutdown_event = asyncio.Event()
    
    def on_startup(self, func: Callable) -> Callable:
        """
        Декоратор для регистрации startup hook
        
        Пример:
        ```python
        @lifecycle.on_startup
        async def init_services():
            ...
        ```
        """
        self._startup_hooks.append(func)
        return func
    
    def on_shutdown(self, func: Callable) -> Callable:
        """
        Декоратор для регистрации shutdown hook
        
        Пример:
        ```python
        @lifecycle.on_shutdown
        async def cleanup_resources():
            ...
        ```
        """
        self._shutdown_hooks.append(func)
        return func
    
    async def startup(self) -> None:
        """Выполнить все startup hooks"""
        logger.info("Running startup hooks…")
        
        for hook in self._startup_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
                logger.debug(f"Startup hook {hook.__name__} completed")
            except Exception as e:
                logger.error(f"Startup hook {hook.__name__} failed: {e}", exc_info=True)
                raise
        
        logger.info(f"All {len(self._startup_hooks)} startup hooks completed")
    
    async def shutdown(self) -> None:
        """Выполнить graceful shutdown"""
        if self._is_shutting_down:
            logger.warning("Shutdown already in progress")
            return
        
        self._is_shutting_down = True
        logger.info("Starting graceful shutdown…")
        
        # Устанавливаем событие shutdown
        self._shutdown_event.set()
        
        # Выполняем shutdown hooks с таймаутом
        try:
            await asyncio.wait_for(
                self._run_shutdown_hooks(),
                timeout=self.shutdown_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Shutdown timeout ({self.shutdown_timeout}s) exceeded")
        
        logger.info("Graceful shutdown completed")
    
    async def _run_shutdown_hooks(self) -> None:
        """Выполнить все shutdown hooks"""
        for hook in reversed(self._shutdown_hooks):  # В обратном порядке
            try:
                logger.debug(f"Running shutdown hook: {hook.__name__}")
                if asyncio.iscoroutinefunction(hook):
                    await hook()
                else:
                    hook()
                logger.debug(f"Shutdown hook {hook.__name__} completed")
            except Exception as e:
                logger.error(f"Shutdown hook {hook.__name__} failed: {e}", exc_info=True)
                # Продолжаем выполнение остальных hooks
        
        logger.info(f"All {len(self._shutdown_hooks)} shutdown hooks completed")
    
    @property
    def is_shutting_down(self) -> bool:
        """Проверить, идёт ли shutdown"""
        return self._is_shutting_down
    
    async def wait_for_shutdown(self) -> None:
        """Ждать сигнала shutdown"""
        await self._shutdown_event.wait()


# =============================================================================
# Global Lifecycle Manager
# =============================================================================

_lifecycle_manager: Optional[LifecycleManager] = None


def get_lifecycle_manager() -> LifecycleManager:
    """Получить глобальный lifecycle manager"""
    global _lifecycle_manager
    if _lifecycle_manager is None:
        _lifecycle_manager = LifecycleManager()
    return _lifecycle_manager


# =============================================================================
# FastAPI Lifespan Context Manager
# =============================================================================

@asynccontextmanager
async def lifespan(app):
    """
    FastAPI lifespan context manager
    
    Использование:
    ```python
    app = FastAPI(lifespan=lifespan)
    ```
    """
    lifecycle = get_lifecycle_manager()
    
    # Startup
    logger.info("Application starting up…")
    await lifecycle.startup()
    
    # Регистрируем обработчики сигналов
    loop = asyncio.get_event_loop()
    
    def signal_handler(sig):
        logger.info(f"Received signal {sig.name}")
        asyncio.create_task(lifecycle.shutdown())
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: signal_handler(s))
        except NotImplementedError:
            # Windows не поддерживает add_signal_handler
            pass
    
    logger.info("Application started successfully")
    
    yield
    
    # Shutdown
    logger.info("Application shutting down…")
    await lifecycle.shutdown()
    logger.info("Application shutdown complete")


# =============================================================================
# Default Hooks
# =============================================================================

def register_default_hooks(lifecycle: LifecycleManager) -> None:
    """Зарегистрировать стандартные hooks"""
    
    @lifecycle.on_startup
    async def init_health_checker():
        """Инициализировать health checker"""
        from app.core.health import get_health_checker
        get_health_checker()
        logger.info("Health checker initialized")
    
    @lifecycle.on_startup
    async def init_metrics():
        """Инициализировать метрики"""
        from app.services.chat.metrics import get_metrics
        get_metrics()
        logger.info("Metrics initialized")
    
    @lifecycle.on_shutdown
    async def cleanup_circuit_breakers():
        """Сбросить circuit breakers"""
        from app.core.resilience import CircuitBreakerRegistry
        CircuitBreakerRegistry.reset_all()
        logger.info("Circuit breakers reset")
    
    @lifecycle.on_shutdown
    async def cleanup_container():
        """Очистить DI контейнер"""
        from app.core.container import Container
        Container.reset()
        logger.info("DI container reset")


# =============================================================================
# Streaming Utilities
# =============================================================================

class StreamingController:
    """
    Контроллер для управления streaming с поддержкой отмены
    
    Позволяет:
    - Отменять streaming при disconnect клиента
    - Backpressure при медленном клиенте
    - Graceful shutdown
    """
    
    def __init__(
        self,
        max_queue_size: int = 100,
        timeout: float = 60.0
    ):
        """
        Инициализация контроллера
        
        Args:
            max_queue_size: Максимальный размер очереди (backpressure)
            timeout: Таймаут ожидания (секунды)
        """
        self.max_queue_size = max_queue_size
        self.timeout = timeout
        self._cancelled = False
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
    
    def cancel(self) -> None:
        """Отменить streaming"""
        self._cancelled = True
    
    @property
    def is_cancelled(self) -> bool:
        """Проверить, отменён ли streaming"""
        lifecycle = get_lifecycle_manager()
        return self._cancelled or lifecycle.is_shutting_down
    
    async def send(self, data: str) -> bool:
        """
        Отправить данные в stream
        
        Args:
            data: Данные для отправки
            
        Returns:
            True если успешно, False если отменено
        """
        if self.is_cancelled:
            return False
        
        try:
            await asyncio.wait_for(
                self._queue.put(data),
                timeout=self.timeout
            )
            return True
        except asyncio.TimeoutError:
            logger.warning("Streaming queue full, dropping data")
            return False
    
    async def receive(self) -> Optional[str]:
        """
        Получить данные из stream
        
        Returns:
            Данные или None если отменено
        """
        if self.is_cancelled:
            return None
        
        try:
            data = await asyncio.wait_for(
                self._queue.get(),
                timeout=self.timeout
            )
            return data
        except asyncio.TimeoutError:
            return None
    
    async def __aiter__(self):
        """Async iterator для streaming"""
        while not self.is_cancelled:
            data = await self.receive()
            if data is None:
                break
            yield data

