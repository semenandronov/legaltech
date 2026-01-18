"""Rate Limiter for LLM calls - Phase 4.1 Implementation

This module provides rate limiting and throttling for LLM calls to prevent
API overload and 429 errors.

Features:
- Token bucket rate limiting (InMemoryRateLimiter)
- Global semaphore for concurrency control
- Configurable via environment variables
"""
import threading
import time
import logging
from typing import Optional, Callable, Any
from functools import wraps
from app.config import config

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """
    Token bucket rate limiter for controlling request rate.
    
    Based on LangChain's InMemoryRateLimiter pattern.
    Uses a token bucket algorithm to allow burst capacity while
    maintaining an average request rate.
    """
    
    def __init__(
        self,
        requests_per_second: float = 1.0,
        check_every_n_seconds: float = 0.1,
        max_bucket_size: int = 10
    ):
        """
        Initialize the rate limiter.
        
        Args:
            requests_per_second: Target rate of requests per second
            check_every_n_seconds: How often to check if we can proceed
            max_bucket_size: Maximum burst capacity (tokens in bucket)
        """
        self.requests_per_second = requests_per_second
        self.check_every_n_seconds = check_every_n_seconds
        self.max_bucket_size = max_bucket_size
        
        # Token bucket state
        self._tokens = float(max_bucket_size)
        self._last_update = time.monotonic()
        self._lock = threading.Lock()
        
        logger.info(
            f"InMemoryRateLimiter initialized: "
            f"rps={requests_per_second}, bucket_size={max_bucket_size}"
        )
    
    def _refill_tokens(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_update
        self._last_update = now
        
        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.requests_per_second
        self._tokens = min(self.max_bucket_size, self._tokens + tokens_to_add)
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire a token from the bucket, blocking if necessary.
        
        Args:
            timeout: Maximum time to wait for a token (None = wait indefinitely)
            
        Returns:
            True if token was acquired, False if timeout
        """
        start_time = time.monotonic()
        
        while True:
            with self._lock:
                self._refill_tokens()
                
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
            
            # Check timeout
            if timeout is not None:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    logger.warning(f"Rate limiter timeout after {elapsed:.2f}s")
                    return False
            
            # Wait before checking again
            time.sleep(self.check_every_n_seconds)
    
    def try_acquire(self) -> bool:
        """
        Try to acquire a token without blocking.
        
        Returns:
            True if token was acquired, False otherwise
        """
        with self._lock:
            self._refill_tokens()
            
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False
    
    @property
    def available_tokens(self) -> float:
        """Get current number of available tokens."""
        with self._lock:
            self._refill_tokens()
            return self._tokens


class LLMSemaphore:
    """
    Global semaphore for controlling concurrent LLM calls.
    
    Limits the number of simultaneous LLM API calls to prevent
    overwhelming the provider and ensure fair resource usage.
    """
    
    def __init__(self, max_concurrent: int = 8):
        """
        Initialize the semaphore.
        
        Args:
            max_concurrent: Maximum number of concurrent LLM calls
        """
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._current_count = 0
        self._lock = threading.Lock()
        
        logger.info(f"LLMSemaphore initialized: max_concurrent={max_concurrent}")
    
    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire the semaphore.
        
        Args:
            timeout: Maximum time to wait (None = wait indefinitely)
            
        Returns:
            True if acquired, False if timeout
        """
        result = self._semaphore.acquire(timeout=timeout)
        if result:
            with self._lock:
                self._current_count += 1
        return result
    
    def release(self) -> None:
        """Release the semaphore."""
        self._semaphore.release()
        with self._lock:
            self._current_count = max(0, self._current_count - 1)
    
    @property
    def current_usage(self) -> int:
        """Get current number of active LLM calls."""
        with self._lock:
            return self._current_count
    
    @property
    def available_slots(self) -> int:
        """Get number of available slots for LLM calls."""
        with self._lock:
            return self._max_concurrent - self._current_count
    
    def __enter__(self):
        """Context manager entry."""
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release()
        return False


class RateLimitedLLMWrapper:
    """
    Wrapper that adds rate limiting to any LLM instance.
    
    This wrapper proxies all calls to the underlying LLM while adding
    rate limiting. It's compatible with LangChain's Runnable interface
    by implementing __or__ and __ror__ for pipe operators.
    
    Note: Pydantic models (like ChatGigaChat) don't allow monkey-patching,
    so we use a wrapper class instead.
    """
    
    def __init__(
        self,
        llm: Any,
        rate_limiter: Optional[InMemoryRateLimiter] = None,
        semaphore: Optional[LLMSemaphore] = None
    ):
        """
        Initialize the wrapper.
        
        Args:
            llm: The underlying LLM instance
            rate_limiter: Rate limiter for request rate control
            semaphore: Semaphore for concurrency control
        """
        # Store in __dict__ directly to avoid __setattr__ issues
        self.__dict__['_llm'] = llm
        self.__dict__['_rate_limiter'] = rate_limiter
        self.__dict__['_semaphore'] = semaphore
    
    def _wait_for_rate_limit(self) -> None:
        """Wait for rate limiter if configured."""
        if self._rate_limiter:
            self._rate_limiter.acquire()
    
    def invoke(self, *args, **kwargs):
        """Invoke the LLM with rate limiting."""
        self._wait_for_rate_limit()
        
        if self._semaphore:
            with self._semaphore:
                return self._llm.invoke(*args, **kwargs)
        return self._llm.invoke(*args, **kwargs)
    
    async def ainvoke(self, *args, **kwargs):
        """Async invoke the LLM with rate limiting."""
        self._wait_for_rate_limit()
        
        if self._semaphore:
            with self._semaphore:
                return await self._llm.ainvoke(*args, **kwargs)
        return await self._llm.ainvoke(*args, **kwargs)
    
    def __or__(self, other):
        """Support pipe operator for LangChain chains: llm | parser"""
        # Create a RunnableSequence manually
        from langchain_core.runnables import RunnableSequence
        return RunnableSequence(first=self, last=other)
    
    def __ror__(self, other):
        """Support reverse pipe operator for LangChain chains: prompt | llm"""
        # Create a RunnableSequence manually
        from langchain_core.runnables import RunnableSequence
        return RunnableSequence(first=other, last=self)
    
    def __getattr__(self, name):
        """Proxy all other attributes to the underlying LLM."""
        # This is called only when attribute is not found in __dict__
        return getattr(self._llm, name)
    
    def __setattr__(self, name, value):
        """Allow setting attributes on the wrapper."""
        if name.startswith('_'):
            self.__dict__[name] = value
        else:
            setattr(self._llm, name, value)
    
    # Runnable interface properties
    @property
    def InputType(self):
        """Return InputType from underlying LLM for Runnable compatibility."""
        return getattr(self._llm, 'InputType', Any)
    
    @property
    def OutputType(self):
        """Return OutputType from underlying LLM for Runnable compatibility."""
        return getattr(self._llm, 'OutputType', Any)
    
    def get_input_schema(self, *args, **kwargs):
        """Proxy to underlying LLM's get_input_schema."""
        if hasattr(self._llm, 'get_input_schema'):
            return self._llm.get_input_schema(*args, **kwargs)
        return None
    
    def get_output_schema(self, *args, **kwargs):
        """Proxy to underlying LLM's get_output_schema."""
        if hasattr(self._llm, 'get_output_schema'):
            return self._llm.get_output_schema(*args, **kwargs)
        return None
    
    def bind(self, **kwargs):
        """Bind arguments to the LLM."""
        if hasattr(self._llm, 'bind'):
            bound_llm = self._llm.bind(**kwargs)
            return RateLimitedLLMWrapper(bound_llm, self._rate_limiter, self._semaphore)
        raise NotImplementedError("Underlying LLM does not support bind()")
    
    def with_config(self, **kwargs):
        """Configure the LLM."""
        if hasattr(self._llm, 'with_config'):
            configured_llm = self._llm.with_config(**kwargs)
            return RateLimitedLLMWrapper(configured_llm, self._rate_limiter, self._semaphore)
        return self


# Global instances (singletons)
_global_rate_limiter: Optional[InMemoryRateLimiter] = None
_global_semaphore: Optional[LLMSemaphore] = None
_init_lock = threading.Lock()


def get_rate_limiter() -> Optional[InMemoryRateLimiter]:
    """
    Get or create the global rate limiter instance.
    
    Returns:
        InMemoryRateLimiter instance or None if disabled
    """
    global _global_rate_limiter
    
    if not config.RATE_LIMIT_ENABLED:
        return None
    
    with _init_lock:
        if _global_rate_limiter is None:
            _global_rate_limiter = InMemoryRateLimiter(
                requests_per_second=config.RATE_LIMIT_RPS,
                check_every_n_seconds=config.RATE_LIMIT_CHECK_INTERVAL,
                max_bucket_size=config.RATE_LIMIT_MAX_BUCKET_SIZE
            )
        return _global_rate_limiter


def get_llm_semaphore() -> LLMSemaphore:
    """
    Get or create the global LLM semaphore instance.
    
    Returns:
        LLMSemaphore instance
    """
    global _global_semaphore
    
    with _init_lock:
        if _global_semaphore is None:
            _global_semaphore = LLMSemaphore(
                max_concurrent=config.MAX_PARALLEL_LLM_CALLS
            )
        return _global_semaphore


def rate_limited(func: Callable) -> Callable:
    """
    Decorator to add rate limiting to a function.
    
    Example:
        @rate_limited
        def call_llm(prompt):
            return llm.invoke(prompt)
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        rate_limiter = get_rate_limiter()
        semaphore = get_llm_semaphore()
        
        if rate_limiter:
            rate_limiter.acquire()
        
        with semaphore:
            return func(*args, **kwargs)
    
    return wrapper


def get_rate_limit_stats() -> dict:
    """
    Get current rate limiting statistics.
    
    Returns:
        Dictionary with rate limiting stats
    """
    rate_limiter = get_rate_limiter()
    semaphore = get_llm_semaphore()
    
    return {
        "rate_limit_enabled": config.RATE_LIMIT_ENABLED,
        "rate_limit_rps": config.RATE_LIMIT_RPS,
        "rate_limit_bucket_size": config.RATE_LIMIT_MAX_BUCKET_SIZE,
        "available_tokens": rate_limiter.available_tokens if rate_limiter else None,
        "max_parallel_llm_calls": config.MAX_PARALLEL_LLM_CALLS,
        "current_llm_usage": semaphore.current_usage if semaphore else 0,
        "available_llm_slots": semaphore.available_slots if semaphore else config.MAX_PARALLEL_LLM_CALLS
    }

