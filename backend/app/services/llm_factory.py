"""Factory for creating LLM instances (GigaChat only)

Phase 4.1: Added rate limiting and throttling support.
Phase 5.0: Added dynamic model selection (Lite/Pro) with connection pooling.
"""
from typing import Optional, Any, Dict
from app.config import config
import logging

logger = logging.getLogger(__name__)

# Кэш экземпляров моделей для connection pooling
_llm_cache: Dict[str, Any] = {}


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    use_rate_limiting: bool = True,
    timeout: float = 120.0,  # Timeout для HTTP запросов (секунды)
    **kwargs
) -> Any:
    """
    Create LLM instance (GigaChat only) with optional rate limiting.
    
    Args:
        provider: "gigachat" (default: from config.LLM_PROVIDER)
        model: Model name (optional)
        temperature: Temperature for generation
        use_rate_limiting: Whether to wrap with rate limiter (default: True)
        timeout: HTTP request timeout in seconds (default: 120s for complex legal queries)
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
                timeout=timeout,
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


def create_llm_for_agent(
    agent_name: str,
    complexity: Optional[str] = None,
    context_size: Optional[int] = None,
    document_count: Optional[int] = None,
    state: Optional[Any] = None,
    temperature: float = 0.1,
    use_rate_limiting: bool = True,
    **kwargs
) -> Any:
    """
    Create LLM instance optimized for specific agent with dynamic model selection.
    
    Uses ModelSelector to choose between GigaChat Lite (simple tasks) and 
    GigaChat Pro (complex tasks) based on agent type, complexity, and context.
    
    Args:
        agent_name: Name of the agent (e.g., "timeline", "risk")
        complexity: Task complexity ("simple", "medium", "high")
        context_size: Size of context in tokens
        document_count: Number of documents
        state: AnalysisState (optional, for extracting complexity)
        temperature: Temperature for generation
        use_rate_limiting: Whether to wrap with rate limiter
        **kwargs: Additional arguments
    
    Returns:
        LLM instance (ChatGigaChat) with appropriate model selected
    """
    from app.services.langchain_agents.model_selector import get_model_selector
    
    # Получить модель через ModelSelector
    model_selector = get_model_selector()
    selected_model = model_selector.select_model(
        agent_name=agent_name,
        state=state,
        complexity=complexity,
        context_size=context_size,
        document_count=document_count
    )
    
    # Кэширование экземпляров моделей для connection pooling
    cache_key = f"{selected_model}_{temperature}_{use_rate_limiting}"
    
    if cache_key in _llm_cache:
        logger.debug(f"Reusing cached LLM instance: {cache_key}")
        return _llm_cache[cache_key]
    
    # Создать новый экземпляр
    llm = create_llm(
        model=selected_model,
        temperature=temperature,
        use_rate_limiting=use_rate_limiting,
        **kwargs
    )
    
    # Сохранить в кэш (ограничить размер кэша)
    if len(_llm_cache) < 10:  # Максимум 10 экземпляров в кэше
        _llm_cache[cache_key] = llm
        logger.debug(f"Cached LLM instance: {cache_key}")
    else:
        logger.debug(f"Cache full, not caching: {cache_key}")
    
    model_info = model_selector.get_model_info(selected_model)
    logger.info(
        f"Created LLM for agent {agent_name}: {selected_model} "
        f"(type: {model_info['type']}, cost: {model_info['cost_tier']})"
    )
    
    return llm


def create_legal_llm(
    model: Optional[str] = None,
    use_rate_limiting: bool = True,
    temperature: Optional[float] = None,
    timeout: float = 180.0,  # Увеличенный timeout для юридических запросов (3 минуты)
    **kwargs
) -> Any:
    """
    Create LLM for legal content generation (temperature=0.0 by default, but can be overridden).
    
    Use this for ALL legal RAG responses and agent outputs.
    Ensures deterministic, factual outputs without hallucinations.
    
    Args:
        model: Model name (optional, uses default from config)
        use_rate_limiting: Whether to wrap with rate limiter (default: True)
        temperature: Temperature override (default: uses config.LLM_TEMPERATURE_LEGAL)
        timeout: HTTP request timeout in seconds (default: 180s for complex legal queries)
        **kwargs: Additional arguments passed to create_llm
    
    Returns:
        LLM instance (ChatGigaChat) with temperature (default 0.0)
    """
    # Use provided temperature or default to legal temperature
    final_temperature = temperature if temperature is not None else config.LLM_TEMPERATURE_LEGAL
    return create_llm(
        model=model,
        temperature=final_temperature,
        use_rate_limiting=use_rate_limiting,
        timeout=timeout,
        **kwargs
    )


def create_verifier_llm(
    use_rate_limiting: bool = True,
    **kwargs
) -> Any:
    """
    Create LLM for citation verification (temperature=0.0).
    
    Use this for verifying that citations match source documents.
    
    Args:
        use_rate_limiting: Whether to wrap with rate limiter (default: True)
        **kwargs: Additional arguments passed to create_llm
    
    Returns:
        LLM instance (ChatGigaChat) with temperature=0.0
    """
    return create_llm(
        temperature=config.LLM_TEMPERATURE_VERIFIER,  # 0.0
        use_rate_limiting=use_rate_limiting,
        **kwargs
    )


def create_judge_llm(
    use_rate_limiting: bool = True,
    **kwargs
) -> Any:
    """
    Create LLM for LLM-as-Judge evaluation (temperature=0.0).
    
    Use this for evaluating whether claims are supported by sources.
    
    Args:
        use_rate_limiting: Whether to wrap with rate limiter (default: True)
        **kwargs: Additional arguments passed to create_llm
    
    Returns:
        LLM instance (ChatGigaChat) with temperature=0.0
    """
    return create_llm(
        temperature=config.LLM_TEMPERATURE_JUDGE,  # 0.0
        use_rate_limiting=use_rate_limiting,
        **kwargs
    )


def clear_llm_cache():
    """Clear the LLM instance cache (useful for testing or memory management)"""
    global _llm_cache
    _llm_cache.clear()
    logger.info("LLM cache cleared")

