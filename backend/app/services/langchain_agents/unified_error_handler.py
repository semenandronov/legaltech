"""Unified error handler for all agents with clear error classification and strategies"""
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass
from app.services.langchain_agents.state import AnalysisState
import logging

logger = logging.getLogger(__name__)


class ErrorType(str, Enum):
    """Types of errors that can occur in agent execution"""
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    LLM_ERROR = "llm_error"
    DEPENDENCY_ERROR = "dependency_error"
    VALIDATION_ERROR = "validation_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN = "unknown"


class ErrorStrategy(str, Enum):
    """Strategies for handling errors"""
    RETRY = "retry"
    FALLBACK = "fallback"
    SKIP = "skip"
    FAIL = "fail"


@dataclass
class ErrorResult:
    """Result of error handling"""
    success: bool
    strategy: ErrorStrategy
    message: str
    retry_after: Optional[float] = None  # Seconds to wait before retry
    should_retry: bool = False
    max_retries: int = 3
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "strategy": self.strategy.value,
            "message": self.message,
            "retry_after": self.retry_after,
            "should_retry": self.should_retry,
            "max_retries": self.max_retries,
            "retry_count": self.retry_count
        }


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
    DEPENDENCY_PATTERNS = ["dependency", "requires", "missing", "not found"]
    NETWORK_PATTERNS = ["connection", "network", "dns", "socket", "http"]
    
    def __init__(self, max_retries: int = 3, base_retry_delay: float = 1.0):
        """
        Initialize unified error handler
        
        Args:
            max_retries: Maximum number of retries for retryable errors
            base_retry_delay: Base delay in seconds for exponential backoff
        """
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
    
    def classify_error(self, error: Exception) -> ErrorType:
        """
        Classify error type based on error message and type
        
        Args:
            error: Exception that occurred
            
        Returns:
            ErrorType classification
        """
        error_str = str(error).lower()
        error_type_name = type(error).__name__.lower()
        
        # Check timeout patterns
        if any(pattern in error_str for pattern in self.TIMEOUT_PATTERNS):
            return ErrorType.TIMEOUT
        
        # Check tool error patterns
        if any(pattern in error_str for pattern in self.TOOL_ERROR_PATTERNS):
            return ErrorType.TOOL_ERROR
        
        # Check LLM error patterns
        if any(pattern in error_str for pattern in self.LLM_ERROR_PATTERNS):
            return ErrorType.LLM_ERROR
        
        # Check dependency patterns
        if any(pattern in error_str for pattern in self.DEPENDENCY_PATTERNS):
            return ErrorType.DEPENDENCY_ERROR
        
        # Check network patterns
        if any(pattern in error_str for pattern in self.NETWORK_PATTERNS):
            return ErrorType.NETWORK_ERROR
        
        # Check error type
        if "timeout" in error_type_name:
            return ErrorType.TIMEOUT
        if "connection" in error_type_name or "network" in error_type_name:
            return ErrorType.NETWORK_ERROR
        if "validation" in error_type_name or "value" in error_type_name:
            return ErrorType.VALIDATION_ERROR
        
        return ErrorType.UNKNOWN
    
    def select_strategy(self, error_type: ErrorType, agent_name: str) -> ErrorStrategy:
        """
        Select error handling strategy based on error type
        
        Args:
            error_type: Classified error type
            agent_name: Name of the agent that failed
            
        Returns:
            ErrorStrategy to use
        """
        # Retryable errors
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
            # Calculate exponential backoff delay
            retry_delay = self.base_retry_delay * (2 ** retry_count)
            
            return ErrorResult(
                success=False,
                strategy=strategy,
                message=f"Error in {agent_name}: {str(error)[:200]}. Will retry after {retry_delay}s",
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
    
    def get_retry_delay(self, retry_count: int) -> float:
        """Calculate retry delay with exponential backoff"""
        return self.base_retry_delay * (2 ** retry_count)

