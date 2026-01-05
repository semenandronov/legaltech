"""Unified error handler for all agents with clear error classification and strategies

Phase 2.3-2.4: Enhanced with production-ready error handling.
"""
from typing import Dict, Any, Optional, List, Callable
from enum import Enum
from dataclasses import dataclass, field
from app.services.langchain_agents.state import AnalysisState
import logging
import time
import traceback

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Types of errors that can occur in agent execution"""
    # LLM errors
    TIMEOUT = "timeout"
    LLM_ERROR = "llm_error"
    LLM_RATE_LIMIT = "llm_rate_limit"
    LLM_TIMEOUT = "llm_timeout"
    LLM_INVALID_RESPONSE = "llm_invalid_response"
    LLM_UNAVAILABLE = "llm_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    
    # Tool errors
    TOOL_ERROR = "tool_error"
    TOOL_TIMEOUT = "tool_timeout"
    
    # Retrieval errors
    RETRIEVER_TIMEOUT = "retriever_timeout"
    RETRIEVER_ERROR = "retriever_error"
    
    # Validation errors
    VALIDATION_ERROR = "validation_error"
    SCHEMA_ERROR = "schema_error"
    INCONSISTENT_OUTPUT = "inconsistent_output"
    
    # Infrastructure errors
    DEPENDENCY_ERROR = "dependency_error"
    NETWORK_ERROR = "network_error"
    DATABASE_ERROR = "database_error"
    CIRCUIT_BREAKER_OPEN = "circuit_breaker_open"
    
    # Other
    UNKNOWN = "unknown"


class ErrorStrategy(str, Enum):
    """Strategies for handling errors"""
    RETRY = "retry"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    FALLBACK = "fallback"
    FALLBACK_RULE_BASED = "fallback_rule_based"
    SKIP = "skip"
    SKIP_AND_CONTINUE = "skip_and_continue"
    FAIL = "fail"
    FAIL_GRACEFULLY = "fail_gracefully"


@dataclass
class ErrorResult:
    """Result of error handling"""
    success: bool
    strategy: ErrorStrategy
    message: str
    error_type: ErrorType = ErrorType.UNKNOWN
    retry_after: Optional[float] = None
    should_retry: bool = False
    max_retries: int = 3
    retry_count: int = 0
    fallback_result: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "strategy": self.strategy.value,
            "error_type": self.error_type.value,
            "message": self.message,
            "retry_after": self.retry_after,
            "should_retry": self.should_retry,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count
        }
        if self.fallback_result:
            result["fallback_result"] = self.fallback_result
        return result


@dataclass
class ErrorContext:
    """Context for error analysis and handling"""
    error: Exception
    agent_name: str
    case_id: str
    operation: str = "unknown"
    attempt: int = 1
    start_time: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def duration(self) -> Optional[float]:
        if self.start_time:
            return time.time() - self.start_time
        return None


class UnifiedErrorHandler:
    """
    Unified error handler for all agents with clear error classification and strategies.
    
    Replaces multiple error handling patterns with a single, consistent approach.
    """
    
    # Error classification patterns
    TIMEOUT_PATTERNS = ["timeout", "timed out", "exceeded", "deadline"]
    TOOL_ERROR_PATTERNS = [
        "bind_tools", "tool use", "function calling", "tools not available",
        "notimplemented", "404", "no endpoints found"
    ]
    LLM_ERROR_PATTERNS = [
        "llm", "model", "api", "rate limit", "quota", "token"
    ]
    LLM_RATE_LIMIT_PATTERNS = [
        "429", "too many requests", "rate limit", "rate_limit", 
        "quota exceeded", "quota_exceeded", "throttle", "throttling"
    ]
    LLM_TIMEOUT_PATTERNS = [
        "timeout", "timed out", "deadline exceeded", "request timeout"
    ]
    LLM_INVALID_RESPONSE_PATTERNS = [
        "invalid response", "parse error", "json decode", "malformed",
        "unexpected format", "schema validation", "invalid format"
    ]
    LLM_UNAVAILABLE_PATTERNS = [
        "503", "service unavailable", "unavailable", "502", "bad gateway",
        "connection refused", "connection error", "cannot connect"
    ]
    DEPENDENCY_PATTERNS = ["dependency", "requires", "missing", "not found"]
    NETWORK_PATTERNS = ["connection", "network", "dns", "socket", "http"]
    
    def __init__(
        self, 
        max_retries: int = 3, 
        base_retry_delay: float = 1.0,
        enable_graceful_degradation: bool = True
    ):
        """
        Initialize unified error handler
        
        Args:
            max_retries: Maximum number of retries for retryable errors
            base_retry_delay: Base delay in seconds for exponential backoff
            enable_graceful_degradation: Enable graceful degradation when services unavailable
        """
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.enable_graceful_degradation = enable_graceful_degradation
    
    def classify_error(self, error: Exception) -> ErrorType:
        """
        Classify error type based on error message and type with detailed LLM error classification
        
        Args:
            error: Exception that occurred
            
        Returns:
            ErrorType classification
        """
        error_str = str(error).lower()
        error_type_name = type(error).__name__.lower()
        
        # Check for detailed LLM error subtypes first (more specific)
        if any(pattern in error_str for pattern in self.LLM_RATE_LIMIT_PATTERNS):
            return ErrorType.LLM_RATE_LIMIT
        
        if any(pattern in error_str for pattern in self.LLM_UNAVAILABLE_PATTERNS):
            return ErrorType.LLM_UNAVAILABLE
        
        if any(pattern in error_str for pattern in self.LLM_TIMEOUT_PATTERNS):
            # Check if it's LLM-specific timeout (not general timeout)
            if any(llm_pattern in error_str for llm_pattern in ["llm", "model", "api", "gigachat", "yandex"]):
                return ErrorType.LLM_TIMEOUT
        
        if any(pattern in error_str for pattern in self.LLM_INVALID_RESPONSE_PATTERNS):
            # Check if it's LLM response parsing error
            if any(llm_pattern in error_str for llm_pattern in ["llm", "model", "response", "generation"]):
                return ErrorType.LLM_INVALID_RESPONSE
        
        # Check general timeout patterns
        if any(pattern in error_str for pattern in self.TIMEOUT_PATTERNS):
            return ErrorType.TIMEOUT
        
        # Check tool error patterns
        if any(pattern in error_str for pattern in self.TOOL_ERROR_PATTERNS):
            return ErrorType.TOOL_ERROR
        
        # Check general LLM error patterns (fallback for other LLM errors)
        if any(pattern in error_str for pattern in self.LLM_ERROR_PATTERNS):
            return ErrorType.LLM_ERROR
        
        # Check dependency patterns
        if any(pattern in error_str for pattern in self.DEPENDENCY_PATTERNS):
            return ErrorType.DEPENDENCY_ERROR
        
        # Check network patterns
        if any(pattern in error_str for pattern in self.NETWORK_PATTERNS):
            return ErrorType.NETWORK_ERROR
        
        # Check error type by class name
        if "timeout" in error_type_name:
            return ErrorType.TIMEOUT
        if "connection" in error_type_name or "network" in error_type_name:
            return ErrorType.NETWORK_ERROR
        if "validation" in error_type_name or "value" in error_type_name:
            return ErrorType.VALIDATION_ERROR
        
        # Check HTTP status codes in error attributes
        if hasattr(error, 'status_code'):
            status_code = error.status_code
            if status_code == 429:
                return ErrorType.LLM_RATE_LIMIT
            elif status_code in [502, 503, 504]:
                return ErrorType.LLM_UNAVAILABLE
            elif status_code == 408:
                return ErrorType.LLM_TIMEOUT
        
        return ErrorType.UNKNOWN
    
    def select_strategy(self, error_type: ErrorType, agent_name: str) -> ErrorStrategy:
        """
        Select error handling strategy based on error type with detailed LLM error handling
        
        Args:
            error_type: Classified error type
            agent_name: Name of the agent that failed
            
        Returns:
            ErrorStrategy to use
        """
        # LLM-specific error strategies
        if error_type == ErrorType.LLM_RATE_LIMIT:
            # Rate limit: retry with longer backoff
            return ErrorStrategy.RETRY
        if error_type == ErrorType.LLM_TIMEOUT:
            # LLM timeout: retry with shorter timeout or simplified request
            return ErrorStrategy.RETRY
        if error_type == ErrorType.LLM_UNAVAILABLE:
            # LLM unavailable: retry (might be transient) or graceful degradation
            return ErrorStrategy.RETRY
        if error_type == ErrorType.LLM_INVALID_RESPONSE:
            # Invalid response: retry (might be parsing error) or fallback
            return ErrorStrategy.RETRY
        
        # General retryable errors
        if error_type in [ErrorType.TIMEOUT, ErrorType.NETWORK_ERROR, ErrorType.LLM_ERROR]:
            return ErrorStrategy.RETRY
        
        # Fallback for tool errors (can use simplified approach)
        if error_type == ErrorType.TOOL_ERROR:
            return ErrorStrategy.FALLBACK
        
        # Skip for dependency errors (will be handled by supervisor)
        if error_type == ErrorType.DEPENDENCY_ERROR:
            return ErrorStrategy.SKIP
        
        # Fail for validation errors (should not be retried)
        if error_type == ErrorType.VALIDATION_ERROR:
            return ErrorStrategy.FAIL
        
        # Default: retry for unknown errors (might be transient)
        return ErrorStrategy.RETRY
    
    def check_circuit_breaker(self, agent_name: str) -> Optional[ErrorResult]:
        """
        Проверить circuit breaker перед выполнением агента
        
        Args:
            agent_name: Имя агента
        
        Returns:
            ErrorResult если circuit открыт, None если можно выполнять
        """
        from app.services.langchain_agents.circuit_breaker import get_circuit_breaker
        
        circuit_breaker = get_circuit_breaker()
        
        if circuit_breaker.is_circuit_open(agent_name):
            state = circuit_breaker.get_state(agent_name)
            logger.warning(
                f"[ErrorHandler] Circuit breaker OPEN for {agent_name}, "
                f"using fallback strategy"
            )
            
            return ErrorResult(
                success=False,
                strategy=ErrorStrategy.FALLBACK,
                error_type=ErrorType.CIRCUIT_BREAKER_OPEN,
                message=f"Circuit breaker is open for {agent_name}, using fallback",
                should_retry=False
            )
        
        return None
    
    def handle_agent_error(
        self,
        agent_name: str,
        error: Exception,
        context: Dict[str, Any],
        retry_count: int = 0
    ) -> ErrorResult:
        """
        Handle agent error with unified strategy
        
        Args:
            agent_name: Name of the agent that failed
            error: Exception that occurred
            context: Additional context (state, case_id, etc.)
            retry_count: Current retry count
            
        Returns:
            ErrorResult with handling strategy
        """
        # Обновить circuit breaker метрики
        from app.services.langchain_agents.circuit_breaker import get_circuit_breaker
        
        circuit_breaker = get_circuit_breaker()
        error_type_str = type(error).__name__
        circuit_breaker.record_error(agent_name, error_type_str)
        
        error_type = self.classify_error(error)
        strategy = self.select_strategy(error_type, agent_name)
        
        logger.info(
            f"[ErrorHandler] Agent {agent_name} failed with {error_type.value} error, "
            f"strategy: {strategy.value}, retry_count: {retry_count}"
        )
        
        # Check if we should retry
        should_retry = (
            strategy == ErrorStrategy.RETRY and
            retry_count < self.max_retries
        )
        
        if should_retry:
            # Calculate exponential backoff delay with different multipliers for different error types
            if error_type == ErrorType.LLM_RATE_LIMIT:
                # Rate limit: longer backoff (3x base delay)
                retry_delay = self.base_retry_delay * 3 * (2 ** retry_count)
            elif error_type == ErrorType.LLM_UNAVAILABLE:
                # Service unavailable: medium backoff (2x base delay)
                retry_delay = self.base_retry_delay * 2 * (2 ** retry_count)
            elif error_type == ErrorType.LLM_TIMEOUT:
                # Timeout: standard backoff
                retry_delay = self.base_retry_delay * (2 ** retry_count)
            else:
                # Other errors: standard exponential backoff
                retry_delay = self.base_retry_delay * (2 ** retry_count)
            
            # Cap maximum delay at 60 seconds
            retry_delay = min(retry_delay, 60.0)
            
            return ErrorResult(
                success=False,
                strategy=strategy,
                message=f"Error in {agent_name}: {str(error)[:200]}. Will retry after {retry_delay:.1f}s",
                retry_after=retry_delay,
                should_retry=True,
                max_retries=self.max_retries,
                retry_count=retry_count + 1
            )
        
        # No retry - return appropriate result
        if strategy == ErrorStrategy.FALLBACK:
            return ErrorResult(
                success=False,
                strategy=strategy,
                message=f"Error in {agent_name}: {str(error)[:200]}. Will try fallback approach",
                should_retry=False
            )
        
        if strategy == ErrorStrategy.SKIP:
            return ErrorResult(
                success=False,
                strategy=strategy,
                message=f"Error in {agent_name}: {str(error)[:200]}. Skipping this agent",
                should_retry=False
            )
        
        # Graceful degradation for LLM unavailable errors after max retries
        if (
            error_type in [ErrorType.LLM_UNAVAILABLE, ErrorType.LLM_RATE_LIMIT] and
            retry_count >= self.max_retries and
            self.enable_graceful_degradation
        ):
            logger.warning(
                f"[ErrorHandler] Graceful degradation for {agent_name} after {retry_count} retries. "
                f"Service unavailable, continuing with reduced functionality."
            )
            return ErrorResult(
                success=False,
                strategy=ErrorStrategy.FALLBACK,
                message=(
                    f"Error in {agent_name}: {str(error)[:200]}. "
                    f"Service unavailable after {retry_count} retries. "
                    f"Graceful degradation enabled - continuing with reduced functionality."
                ),
                should_retry=False
            )
        
        # FAIL strategy
        return ErrorResult(
            success=False,
            strategy=strategy,
            message=f"Error in {agent_name}: {str(error)[:200]}. Cannot recover",
            should_retry=False
        )
    
    def should_retry(self, error_result: ErrorResult) -> bool:
        """Check if error should be retried"""
        return error_result.should_retry and error_result.retry_count <= error_result.max_retries
    
    def get_retry_delay(self, retry_count: int, error_type: Optional[ErrorType] = None) -> float:
        """
        Calculate retry delay with exponential backoff
        
        Args:
            retry_count: Current retry count
            error_type: Optional error type for specialized delay calculation
            
        Returns:
            Retry delay in seconds (capped at 60 seconds)
        """
        if error_type == ErrorType.LLM_RATE_LIMIT:
            # Rate limit: longer backoff (3x base delay)
            delay = self.base_retry_delay * 3 * (2 ** retry_count)
        elif error_type == ErrorType.LLM_UNAVAILABLE:
            # Service unavailable: medium backoff (2x base delay)
            delay = self.base_retry_delay * 2 * (2 ** retry_count)
        else:
            # Standard exponential backoff
            delay = self.base_retry_delay * (2 ** retry_count)
        
        # Cap maximum delay at 60 seconds
        return min(delay, 60.0)

