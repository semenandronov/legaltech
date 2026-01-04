"""Factory for creating LLM instances (GigaChat only)

Phase 4.1: Added rate limiting and throttling support.
"""
from typing import Optional, Any
from app.config import config
import logging

logger = logging.getLogger(__name__)


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    use_rate_limiting: bool = True,
    **kwargs
) -> Any:
    """
    Create LLM instance (GigaChat only) with optional rate limiting.
    
    Args:
        provider: "gigachat" (default: from config.LLM_PROVIDER)
        model: Model name (optional)
        temperature: Temperature for generation
        use_rate_limiting: Whether to wrap with rate limiter (default: True)
        **kwargs: Additional arguments
    
    Returns:
        LLM instance (ChatGigaChat), optionally wrapped with rate limiting
    """
    provider = provider or config.LLM_PROVIDER or "gigachat"
    provider = provider.lower()
    
    if provider == "gigachat":
        try:
            # Используем наш кастомный wrapper (совместим с langchain-core 1.2.2)
            # langchain-gigachat требует langchain-core<0.4, что несовместимо с нашими версиями
            from app.services.gigachat_llm import ChatGigaChat
            
            if not config.GIGACHAT_CREDENTIALS:
                raise ValueError(
                    "GIGACHAT_CREDENTIALS not set. "
                    "Set GIGACHAT_CREDENTIALS in environment variables."
                )
            
            llm = ChatGigaChat(
                credentials=config.GIGACHAT_CREDENTIALS,
                model=model or config.GIGACHAT_MODEL,
                temperature=temperature,
                verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
                **kwargs
            )
            
            # Wrap with rate limiting if enabled
            if use_rate_limiting and config.RATE_LIMIT_ENABLED:
                try:
                    from app.services.rate_limiter import (
                        RateLimitedLLMWrapper,
                        get_rate_limiter,
                        get_llm_semaphore
                    )
                    
                    llm = RateLimitedLLMWrapper(
                        llm=llm,
                        rate_limiter=get_rate_limiter(),
                        semaphore=get_llm_semaphore()
                    )
                    logger.info(
                        f"Using GigaChat LLM with rate limiting "
                        f"(rps={config.RATE_LIMIT_RPS}, max_parallel={config.MAX_PARALLEL_LLM_CALLS})"
                    )
                except ImportError as rate_error:
                    logger.warning(f"Rate limiting not available: {rate_error}")
            else:
                logger.info("Using GigaChat LLM without rate limiting")
            
            return llm
            
        except ImportError as e:
            raise ImportError(
                f"GigaChat SDK not available ({e}). "
                "Install with: pip install gigachat"
            )
        except Exception as e:
            logger.error(f"Failed to initialize GigaChat: {e}")
            raise
    
    raise ValueError(
        f"Unknown LLM provider: {provider}. "
        "Only 'gigachat' is supported."
    )


def create_llm_without_rate_limiting(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    **kwargs
) -> Any:
    """
    Create LLM instance without rate limiting.
    
    Use this for internal operations where rate limiting
    would cause issues (e.g., streaming, batch processing).
    
    Args:
        provider: "gigachat" (default: from config.LLM_PROVIDER)
        model: Model name (optional)
        temperature: Temperature for generation
        **kwargs: Additional arguments
    
    Returns:
        LLM instance (ChatGigaChat) without rate limiting wrapper
    """
    return create_llm(
        provider=provider,
        model=model,
        temperature=temperature,
        use_rate_limiting=False,
        **kwargs
    )

