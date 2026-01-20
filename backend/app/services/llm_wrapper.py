"""
LLM Wrapper - Обёртка для LLM с resilience

Предоставляет:
- Retry с exponential backoff
- Circuit Breaker
- Timeout
- Fallback
- Метрики
"""
from typing import Any, List, Optional, AsyncGenerator
from langchain_core.messages import BaseMessage, AIMessage
import logging
import time

from app.core.resilience import (
    CircuitBreakerRegistry,
    CircuitBreakerError,
    CircuitBreakerConfig,
    retry,
    RetryConfig,
    with_timeout,
    with_fallback,
    Bulkhead,
)
from app.services.chat.metrics import get_metrics

logger = logging.getLogger(__name__)

# =============================================================================
# Circuit Breaker и Bulkhead для LLM
# =============================================================================

LLM_CIRCUIT_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    success_threshold=2,
    timeout=60.0  # Время в OPEN состоянии
)

llm_circuit = CircuitBreakerRegistry.get("llm", LLM_CIRCUIT_CONFIG)

# Ограничиваем параллельные вызовы LLM
llm_bulkhead = Bulkhead("llm_calls", max_concurrent=10)

# Retry конфигурация для LLM
LLM_RETRY_CONFIG = RetryConfig(
    max_attempts=3,
    initial_delay=2.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=True
)


# =============================================================================
# Resilient LLM Wrapper
# =============================================================================

class ResilientLLM:
    """
    Обёртка для LLM с встроенной устойчивостью к сбоям.
    
    Features:
    - Retry с exponential backoff
    - Circuit Breaker
    - Timeout
    - Bulkhead (ограничение параллелизма)
    - Метрики
    """
    
    def __init__(
        self,
        llm: Any,
        timeout: float = 60.0,
        max_retries: int = 3,
        enable_circuit_breaker: bool = True,
        enable_bulkhead: bool = True
    ):
        """
        Инициализация обёртки
        
        Args:
            llm: Базовый LLM (ChatGigaChat, etc.)
            timeout: Таймаут для вызовов (секунды)
            max_retries: Максимальное количество попыток
            enable_circuit_breaker: Включить circuit breaker
            enable_bulkhead: Включить ограничение параллелизма
        """
        self.llm = llm
        self.timeout = timeout
        self.max_retries = max_retries
        self.enable_circuit_breaker = enable_circuit_breaker
        self.enable_bulkhead = enable_bulkhead
        self.metrics = get_metrics()
    
    async def invoke(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> AIMessage:
        """
        Вызвать LLM с retry и circuit breaker
        
        Args:
            messages: Сообщения для LLM
            **kwargs: Дополнительные параметры
            
        Returns:
            AIMessage с ответом
        """
        start_time = time.time()
        
        try:
            # Проверяем circuit breaker
            if self.enable_circuit_breaker and not llm_circuit.can_execute():
                logger.warning("LLM circuit breaker is OPEN")
                self.metrics.record_external_call("llm", success=False, reason="circuit_open")
                raise CircuitBreakerError("LLM service unavailable")
            
            # Выполняем с bulkhead
            if self.enable_bulkhead:
                async with llm_bulkhead:
                    result = await self._invoke_with_retry(messages, **kwargs)
            else:
                result = await self._invoke_with_retry(messages, **kwargs)
            
            # Записываем успех
            duration = time.time() - start_time
            self.metrics.record_external_call("llm", success=True)
            logger.debug(f"LLM invoke completed in {duration:.2f}s")
            
            # Обновляем circuit breaker
            if self.enable_circuit_breaker:
                llm_circuit._record_success()
            
            return result
            
        except CircuitBreakerError:
            raise
        except Exception as e:
            duration = time.time() - start_time
            self.metrics.record_external_call("llm", success=False, reason=type(e).__name__)
            
            if self.enable_circuit_breaker:
                llm_circuit._record_failure()
            
            logger.error(f"LLM invoke failed after {duration:.2f}s: {e}")
            raise
    
    async def _invoke_with_retry(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> AIMessage:
        """Вызов с retry"""
        import asyncio
        
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                # Проверяем есть ли ainvoke
                if hasattr(self.llm, 'ainvoke'):
                    result = await asyncio.wait_for(
                        self.llm.ainvoke(messages, **kwargs),
                        timeout=self.timeout
                    )
                else:
                    # Fallback на синхронный вызов
                    result = await asyncio.wait_for(
                        asyncio.to_thread(self.llm.invoke, messages, **kwargs),
                        timeout=self.timeout
                    )
                
                return result
                
            except asyncio.TimeoutError:
                last_error = TimeoutError(f"LLM timeout after {self.timeout}s")
                logger.warning(f"LLM timeout (attempt {attempt + 1}/{self.max_retries})")
                
            except Exception as e:
                last_error = e
                logger.warning(f"LLM error (attempt {attempt + 1}/{self.max_retries}): {e}")
            
            # Exponential backoff
            if attempt < self.max_retries - 1:
                delay = LLM_RETRY_CONFIG.initial_delay * (LLM_RETRY_CONFIG.exponential_base ** attempt)
                delay = min(delay, LLM_RETRY_CONFIG.max_delay)
                await asyncio.sleep(delay)
        
        raise last_error or Exception("LLM invoke failed after all retries")
    
    async def stream(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """
        Streaming вызов LLM
        
        Args:
            messages: Сообщения для LLM
            **kwargs: Дополнительные параметры
            
        Yields:
            Чанки текста
        """
        start_time = time.time()
        
        try:
            if self.enable_circuit_breaker and not llm_circuit.can_execute():
                logger.warning("LLM circuit breaker is OPEN")
                self.metrics.record_external_call("llm", success=False, reason="circuit_open")
                raise CircuitBreakerError("LLM service unavailable")
            
            if self.enable_bulkhead:
                async with llm_bulkhead:
                    async for chunk in self._stream_with_timeout(messages, **kwargs):
                        yield chunk
            else:
                async for chunk in self._stream_with_timeout(messages, **kwargs):
                    yield chunk
            
            duration = time.time() - start_time
            self.metrics.record_external_call("llm", success=True)
            
            if self.enable_circuit_breaker:
                llm_circuit._record_success()
            
            logger.debug(f"LLM stream completed in {duration:.2f}s")
            
        except CircuitBreakerError:
            raise
        except Exception as e:
            duration = time.time() - start_time
            self.metrics.record_external_call("llm", success=False, reason=type(e).__name__)
            
            if self.enable_circuit_breaker:
                llm_circuit._record_failure()
            
            logger.error(f"LLM stream failed after {duration:.2f}s: {e}")
            raise
    
    async def _stream_with_timeout(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Streaming с таймаутом"""
        import asyncio
        
        # Проверяем есть ли astream
        if hasattr(self.llm, 'astream'):
            async for chunk in self.llm.astream(messages, **kwargs):
                if hasattr(chunk, 'content'):
                    yield chunk.content
                else:
                    yield str(chunk)
        else:
            # Fallback на обычный invoke
            result = await self.invoke(messages, **kwargs)
            if hasattr(result, 'content'):
                yield result.content
            else:
                yield str(result)


# =============================================================================
# Factory функции
# =============================================================================

def create_resilient_llm(
    temperature: float = 0.3,
    max_tokens: int = 4000,
    model: Optional[str] = None,
    **kwargs
) -> ResilientLLM:
    """
    Создать resilient LLM
    
    Args:
        temperature: Температура генерации
        max_tokens: Максимальное количество токенов
        model: Модель (по умолчанию из конфига)
        **kwargs: Дополнительные параметры
        
    Returns:
        ResilientLLM instance
    """
    from app.services.llm_factory import create_llm
    
    base_llm = create_llm(
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        **kwargs
    )
    
    return ResilientLLM(
        llm=base_llm,
        timeout=60.0,
        max_retries=3,
        enable_circuit_breaker=True,
        enable_bulkhead=True
    )


def create_resilient_legal_llm(**kwargs) -> ResilientLLM:
    """
    Создать resilient LLM для юридических задач (GigaChat Pro)
    
    Returns:
        ResilientLLM instance
    """
    from app.services.llm_factory import create_legal_llm
    
    base_llm = create_legal_llm(**kwargs)
    
    return ResilientLLM(
        llm=base_llm,
        timeout=120.0,  # Больше таймаут для сложных задач
        max_retries=2,
        enable_circuit_breaker=True,
        enable_bulkhead=True
    )


# =============================================================================
# Fallback LLM
# =============================================================================

class FallbackLLM:
    """
    LLM с автоматическим fallback на альтернативную модель
    
    Если основная модель недоступна, использует запасную.
    """
    
    def __init__(
        self,
        primary: ResilientLLM,
        fallback: ResilientLLM
    ):
        """
        Инициализация
        
        Args:
            primary: Основной LLM
            fallback: Запасной LLM
        """
        self.primary = primary
        self.fallback = fallback
        self.metrics = get_metrics()
    
    async def invoke(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> AIMessage:
        """Вызов с fallback"""
        try:
            return await self.primary.invoke(messages, **kwargs)
        except Exception as e:
            logger.warning(f"Primary LLM failed: {e}, falling back")
            self.metrics.record_external_call("llm_fallback", success=True)
            return await self.fallback.invoke(messages, **kwargs)
    
    async def stream(
        self,
        messages: List[BaseMessage],
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """Streaming с fallback"""
        try:
            async for chunk in self.primary.stream(messages, **kwargs):
                yield chunk
        except Exception as e:
            logger.warning(f"Primary LLM stream failed: {e}, falling back")
            self.metrics.record_external_call("llm_fallback", success=True)
            async for chunk in self.fallback.stream(messages, **kwargs):
                yield chunk


def create_llm_with_fallback() -> FallbackLLM:
    """
    Создать LLM с fallback
    
    Primary: GigaChat Pro
    Fallback: GigaChat Lite
    """
    primary = create_resilient_legal_llm()
    fallback = create_resilient_llm(temperature=0.1, max_tokens=2000)
    
    return FallbackLLM(primary=primary, fallback=fallback)

