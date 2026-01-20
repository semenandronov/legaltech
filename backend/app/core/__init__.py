"""
Core module - Ядро приложения

Содержит:
- container: Dependency Injection контейнер
- resilience: Retry, Circuit Breaker, Timeout
- rate_limiter: Rate limiting
- errors: Централизованная обработка ошибок
- health: Health checks
- logging: Structured logging
"""

from app.core.container import (
    Container,
    get_container,
    get_rag_service,
    get_document_processor,
    get_chat_orchestrator,
    get_classifier,
    get_history_service,
)

from app.core.resilience import (
    retry,
    RetryConfig,
    RetryError,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    with_timeout,
    with_fallback,
    Bulkhead,
    LLM_RETRY_CONFIG,
    EXTERNAL_API_RETRY_CONFIG,
)

from app.core.rate_limiter import (
    RateLimiter,
    RateLimitMiddleware,
    RateLimitExceeded,
    rate_limit,
    get_rate_limiter,
)

from app.core.errors import (
    ErrorCode,
    AppException,
    AuthenticationError,
    AuthorizationError,
    ValidationError,
    ResourceNotFoundError,
    CaseNotFoundError,
    DocumentNotFoundError,
    NoDocumentsError,
    LLMError,
    ExternalServiceError,
    RateLimitError,
    register_exception_handlers,
)

from app.core.health import (
    HealthChecker,
    HealthStatus,
    HealthReport,
    ComponentHealth,
    get_health_checker,
)

from app.core.logging import (
    get_logger,
    get_correlation_id,
    set_correlation_id,
    RequestLoggingMiddleware,
    log_performance,
    setup_logging,
)

from app.core.lifecycle import (
    LifecycleManager,
    get_lifecycle_manager,
    lifespan,
    StreamingController,
)

from app.core.validation import (
    ChatRequestInput,
    MessageInput,
    sanitize_input,
    sanitize_html,
    validate_uuid,
    check_injection_attempt,
    check_prompt_injection,
)

__all__ = [
    # Container
    "Container",
    "get_container",
    "get_rag_service",
    "get_document_processor",
    "get_chat_orchestrator",
    "get_classifier",
    "get_history_service",
    # Resilience
    "retry",
    "RetryConfig",
    "RetryError",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerRegistry",
    "with_timeout",
    "with_fallback",
    "Bulkhead",
    "LLM_RETRY_CONFIG",
    "EXTERNAL_API_RETRY_CONFIG",
    # Rate Limiting
    "RateLimiter",
    "RateLimitMiddleware",
    "RateLimitExceeded",
    "rate_limit",
    "get_rate_limiter",
    # Errors
    "ErrorCode",
    "AppException",
    "AuthenticationError",
    "AuthorizationError",
    "ValidationError",
    "ResourceNotFoundError",
    "CaseNotFoundError",
    "DocumentNotFoundError",
    "NoDocumentsError",
    "LLMError",
    "ExternalServiceError",
    "RateLimitError",
    "register_exception_handlers",
    # Health
    "HealthChecker",
    "HealthStatus",
    "HealthReport",
    "ComponentHealth",
    "get_health_checker",
    # Logging
    "get_logger",
    "get_correlation_id",
    "set_correlation_id",
    "RequestLoggingMiddleware",
    "log_performance",
    "setup_logging",
    # Lifecycle
    "LifecycleManager",
    "get_lifecycle_manager",
    "lifespan",
    "StreamingController",
    # Validation
    "ChatRequestInput",
    "MessageInput",
    "sanitize_input",
    "sanitize_html",
    "validate_uuid",
    "check_injection_attempt",
    "check_prompt_injection",
]


