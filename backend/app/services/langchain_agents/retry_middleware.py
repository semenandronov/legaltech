"""Retry Middleware - Phase 4.3 Implementation

This module provides retry policies, circuit breakers, and
adaptive timeouts for robust agent execution.

Features:
- Exponential backoff with jitter
- Circuit breaker pattern
- Adaptive timeout calculation
- Per-node retry policies
"""
from typing import Optional, Callable, Any, Dict
from functools import wraps
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import random
import time
import threading
import logging

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    exponential_base: float = 2.0
    jitter: float = 0.1  # 10% jitter
    
    # Retry on specific exceptions
    retry_exceptions: tuple = (Exception,)
    
    # Don't retry on these exceptions
    fatal_exceptions: tuple = ()
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt with jitter."""
        delay = min(
            self.base_delay * (self.exponential_base ** attempt),
            self.max_delay
        )
        
        # Add jitter
        jitter_amount = delay * self.jitter
        delay += random.uniform(-jitter_amount, jitter_amount)
        
        return max(0.1, delay)


@dataclass
class CircuitBreakerState:
    """State for circuit breaker pattern."""
    
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: str = "closed"  # closed, open, half-open
    
    # Configuration
    failure_threshold: int = 5
    success_threshold: int = 2  # Successes needed in half-open to close
    reset_timeout: timedelta = field(default_factory=lambda: timedelta(seconds=60))
    
    def should_allow_request(self) -> bool:
        """Check if request should be allowed through."""
        if self.state == "closed":
            return True
        
        if self.state == "open":
            # Check if reset timeout has passed
            if self.last_failure_time:
                time_since_failure = datetime.now() - self.last_failure_time
                if time_since_failure >= self.reset_timeout:
                    self.state = "half-open"
                    return True
            return False
        
        # half-open: allow request for testing
        return True
    
    def record_success(self):
        """Record a successful request."""
        if self.state == "half-open":
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = "closed"
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker closed after successful requests")
        elif self.state == "closed":
            # Reset failure count on success
            self.failure_count = 0
    
    def record_failure(self):
        """Record a failed request."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == "half-open":
            # Single failure in half-open reopens circuit
            self.state = "open"
            self.success_count = 0
            logger.warning("Circuit breaker reopened after failure in half-open state")
        elif self.state == "closed":
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(
                    f"Circuit breaker opened after {self.failure_count} failures"
                )


class CircuitBreaker:
    """
    Circuit breaker for protecting external service calls.
    
    Prevents repeated calls to failing services, allowing
    them time to recover.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        reset_timeout: float = 60.0  # seconds
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures to open circuit
            success_threshold: Successes in half-open to close
            reset_timeout: Seconds before attempting recovery
        """
        self._state = CircuitBreakerState(
            failure_threshold=failure_threshold,
            success_threshold=success_threshold,
            reset_timeout=timedelta(seconds=reset_timeout)
        )
        self._lock = threading.Lock()
    
    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        with self._lock:
            return self._state.state == "open"
    
    @property
    def state(self) -> str:
        """Get current circuit state."""
        with self._lock:
            return self._state.state
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator for protecting a function with circuit breaker."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            with self._lock:
                if not self._state.should_allow_request():
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker is open, request blocked"
                    )
            
            try:
                result = func(*args, **kwargs)
                with self._lock:
                    self._state.record_success()
                return result
            except Exception as e:
                with self._lock:
                    self._state.record_failure()
                raise
        
        return wrapper
    
    def record_success(self):
        """Manually record success."""
        with self._lock:
            self._state.record_success()
    
    def record_failure(self):
        """Manually record failure."""
        with self._lock:
            self._state.record_failure()
    
    def reset(self):
        """Reset circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitBreakerState(
                failure_threshold=self._state.failure_threshold,
                success_threshold=self._state.success_threshold,
                reset_timeout=self._state.reset_timeout
            )


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class AdaptiveTimeout:
    """
    Adaptive timeout calculator based on historical latencies.
    
    Calculates timeout as: k * p99 + margin
    where k is a multiplier and margin is a fixed buffer.
    """
    
    def __init__(
        self,
        base_timeout: float = 30.0,
        k_multiplier: float = 2.0,
        margin: float = 5.0,
        window_size: int = 100
    ):
        """
        Initialize adaptive timeout.
        
        Args:
            base_timeout: Default timeout when no history
            k_multiplier: Multiplier for p99 latency
            margin: Fixed margin to add (seconds)
            window_size: Number of samples to keep
        """
        self.base_timeout = base_timeout
        self.k_multiplier = k_multiplier
        self.margin = margin
        self.window_size = window_size
        
        self._latencies: list = []
        self._lock = threading.Lock()
    
    def record_latency(self, latency: float):
        """Record a latency measurement."""
        with self._lock:
            self._latencies.append(latency)
            if len(self._latencies) > self.window_size:
                self._latencies = self._latencies[-self.window_size:]
    
    def get_timeout(self) -> float:
        """Calculate adaptive timeout."""
        with self._lock:
            if len(self._latencies) < 5:
                return self.base_timeout
            
            sorted_latencies = sorted(self._latencies)
            p99_index = int(len(sorted_latencies) * 0.99)
            p99 = sorted_latencies[min(p99_index, len(sorted_latencies) - 1)]
            
            timeout = self.k_multiplier * p99 + self.margin
            return max(self.base_timeout * 0.5, timeout)


def with_retry(
    policy: Optional[RetryPolicy] = None,
    circuit_breaker: Optional[CircuitBreaker] = None
) -> Callable:
    """
    Decorator for adding retry logic with optional circuit breaker.
    
    Args:
        policy: Retry policy configuration
        circuit_breaker: Optional circuit breaker
        
    Returns:
        Decorated function with retry logic
    """
    if policy is None:
        policy = RetryPolicy()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check circuit breaker
            if circuit_breaker and circuit_breaker.is_open:
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open for {func.__name__}"
                )
            
            last_exception = None
            
            for attempt in range(policy.max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    
                    # Record success
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    
                    return result
                    
                except policy.fatal_exceptions as e:
                    # Don't retry fatal exceptions
                    if circuit_breaker:
                        circuit_breaker.record_failure()
                    raise
                    
                except policy.retry_exceptions as e:
                    last_exception = e
                    
                    if attempt < policy.max_retries:
                        delay = policy.get_delay(attempt)
                        logger.warning(
                            f"Retry {attempt + 1}/{policy.max_retries} "
                            f"for {func.__name__} after {delay:.2f}s: {e}"
                        )
                        time.sleep(delay)
                    else:
                        if circuit_breaker:
                            circuit_breaker.record_failure()
            
            # All retries exhausted
            raise last_exception
        
        return wrapper
    return decorator


# Default policies for different operations
MODEL_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    jitter=0.2
)

TOOL_RETRY_POLICY = RetryPolicy(
    max_retries=2,
    base_delay=0.5,
    max_delay=10.0,
    exponential_base=1.5,
    jitter=0.1
)

RETRIEVER_RETRY_POLICY = RetryPolicy(
    max_retries=2,
    base_delay=0.5,
    max_delay=5.0,
    exponential_base=1.5,
    jitter=0.1
)


# Global circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_breaker_lock = threading.Lock()


def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Get or create a named circuit breaker."""
    with _breaker_lock:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker()
        return _circuit_breakers[name]


def get_all_circuit_breakers() -> Dict[str, str]:
    """Get status of all circuit breakers."""
    with _breaker_lock:
        return {name: cb.state for name, cb in _circuit_breakers.items()}

