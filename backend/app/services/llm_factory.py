"""Factory for creating LLM instances (Yandex Model Gallery / GigaChat).

Phase 4.1: Added rate limiting and throttling support.
Phase 5.0: Added dynamic model selection (Lite/Pro) with connection pooling.
"""
from typing import Optional, Any, Dict
import os
import threading
from app.config import clean_env_str, config
import logging
from app.services.observability.langfuse_service import trace_event

logger = logging.getLogger(__name__)

# Кэш экземпляров моделей для connection pooling
_llm_cache: Dict[str, Any] = {}
_llm_cache_lock = threading.Lock()


def _attach_langfuse_llm_instrumentation(llm: Any) -> Any:
    """Wrap LLM so every invoke/stream emits Langfuse generation spans."""
    try:
        from app.services.observability.llm_langfuse_instrumentation import (
            apply_langfuse_llm_instrumentation,
        )

        return apply_langfuse_llm_instrumentation(llm, tags=["assistant", "llm"])
    except Exception:
        logger.debug("Langfuse LLM instrumentation skipped", exc_info=True)
        return llm


def _normalize_cache_part(value: Any) -> str:
    if isinstance(value, (str, int, float, bool, type(None))):
        return str(value)
    if isinstance(value, dict):
        items = sorted((str(k), _normalize_cache_part(v)) for k, v in value.items())
        return "{" + ",".join(f"{k}:{v}" for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_normalize_cache_part(v) for v in value) + "]"
    return repr(value)


def _build_llm_cache_key(
    *,
    provider: str,
    model: Optional[str],
    temperature: float,
    use_rate_limiting: bool,
    timeout: float,
    kwargs: Dict[str, Any],
) -> str:
    kwargs_norm = _normalize_cache_part(kwargs)
    model_norm = (model or "").strip()
    return "|".join(
        [
            f"provider={provider}",
            f"model={model_norm}",
            f"temp={temperature}",
            f"rl={use_rate_limiting}",
            f"timeout={timeout}",
            f"kwargs={kwargs_norm}",
        ]
    )


def default_yandex_max_tokens() -> int:
    """
    Лимит max_tokens для Foundation Models (gRPC).

    DeepSeek-V3.2 (Model Gallery): по документации — до 32 768 выходных токенов в режиме рассуждений
    (по умолчанию у модели рассуждения включены; отключение через OpenAI API: reasoning_effort \"none\"),
    без рассуждений — до 8 192 (часто используют 4096).
    """
    explicit = getattr(config, "YANDEX_GPT_MAX_TOKENS", 0) or 0
    if explicit > 0:
        return min(int(explicit), 100_000)

    uri = (config.YANDEX_GPT_MODEL_URI or "").lower()
    rm = (getattr(config, "YANDEX_REASONING_MODE", None) or "").strip().lower()

    if "deepseek" in uri:
        if rm == "disabled":
            return min(int(os.getenv("YANDEX_DEEPSEEK_MAX_TOKENS_NO_REASONING", "4096")), 8192)
        return min(int(os.getenv("YANDEX_DEEPSEEK_MAX_TOKENS_REASONING", "32768")), 32768)

    return int(os.getenv("YANDEX_LEGACY_MAX_TOKENS", "7400"))


def legal_deep_extra_kwargs() -> Dict[str, Any]:
    """
    Доп. аргументы для «усиленного» режима (deep_think / GigaChat Pro / Yandex + reasoning).

    - GigaChat: модель Pro.
    - Yandex: опционально reasoning_mode из YANDEX_DEEP_REASONING_MODE (иначе — общий YANDEX_REASONING_MODE в ChatYandexGPT).
    """
    provider = clean_env_str(config.LLM_PROVIDER or "yandex").lower()
    if provider == "gigachat":
        return {"model": config.GIGACHAT_PRO_MODEL or "GigaChat-Pro"}
    extra: Dict[str, Any] = {}
    deep_rm = clean_env_str(os.getenv("YANDEX_DEEP_REASONING_MODE")).lower()
    if deep_rm:
        extra["reasoning_mode"] = deep_rm
    return extra


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    use_rate_limiting: bool = True,
    timeout: float = 120.0,  # Timeout для HTTP запросов (секунды)
    **kwargs
) -> Any:
    """
    Create LLM instance (Yandex или GigaChat) with optional rate limiting.
    
    Args:
        provider: "yandex" | "gigachat" (default: config.LLM_PROVIDER)
        model: Имя модели (опционально; для Yandex чаще задаётся YANDEX_GPT_MODEL_URI)
        temperature: Temperature for generation
        use_rate_limiting: Whether to wrap with rate limiter (default: True)
        timeout: Только для GigaChat (секунды HTTP)
        **kwargs: Доп. аргументы (например max_tokens, reasoning_mode для Yandex gRPC)
    
    Returns:
        Экземпляр LLM, опционально обёрнутый в rate limiting
    """
    provider = clean_env_str(provider or config.LLM_PROVIDER or "yandex").lower()
    llm_kwargs = dict(kwargs)
    cache_enabled = bool(llm_kwargs.pop("cache_enabled", True))
    cache_key = _build_llm_cache_key(
        provider=provider,
        model=model,
        temperature=temperature,
        use_rate_limiting=use_rate_limiting,
        timeout=timeout,
        kwargs=llm_kwargs,
    )
    if cache_enabled:
        with _llm_cache_lock:
            cached = _llm_cache.get(cache_key)
        if cached is not None:
            logger.debug("Reusing cached LLM instance: %s", cache_key)
            return cached
    
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
            
            effective_model = model or config.GIGACHAT_MODEL
            logger.info("Creating GigaChat LLM: model=%s temperature=%s", effective_model, temperature)
            trace_event(
                name="llm_factory_create",
                metadata={
                    "provider": "gigachat",
                    "model": effective_model,
                    "temperature": temperature,
                },
            )
            llm = ChatGigaChat(
                credentials=config.GIGACHAT_CREDENTIALS,
                model=effective_model,
                temperature=temperature,
                verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
                timeout=timeout,
                **llm_kwargs
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
            
            if cache_enabled:
                with _llm_cache_lock:
                    if len(_llm_cache) < 64:
                        _llm_cache[cache_key] = llm
            return _attach_langfuse_llm_instrumentation(llm)
            
        except ImportError as e:
            raise ImportError(
                f"GigaChat SDK not available ({e}). "
                "Install with: pip install gigachat"
            )
        except Exception as e:
            logger.error(f"Failed to initialize GigaChat: {e}")
            raise

    if provider == "yandex":
        if not (config.YANDEX_API_KEY or config.YANDEX_IAM_TOKEN):
            raise ValueError(
                "LLM_PROVIDER=yandex: задайте YANDEX_API_KEY или YANDEX_IAM_TOKEN."
            )
        if not (config.YANDEX_GPT_MODEL_URI or config.YANDEX_FOLDER_ID):
            raise ValueError(
                "LLM_PROVIDER=yandex: задайте YANDEX_GPT_MODEL_URI (рекомендуется) или YANDEX_FOLDER_ID."
            )

        yandex_kwargs = dict(llm_kwargs)
        yandex_kwargs.pop("timeout", None)
        if "max_tokens" not in yandex_kwargs:
            yandex_kwargs["max_tokens"] = default_yandex_max_tokens()

        transport = (
            getattr(config, "YANDEX_LLM_TRANSPORT", None)
            or os.getenv("YANDEX_LLM_TRANSPORT", "grpc")
        ).strip().lower()

        effective_model = (model or config.YANDEX_GPT_MODEL_URI or "").strip()
        logger.info(
            "Creating Yandex LLM: transport=%s model=%s uri=%s temperature=%s max_tokens=%s",
            transport,
            effective_model,
            (config.YANDEX_GPT_MODEL_URI or "")[:48],
            temperature,
            yandex_kwargs.get("max_tokens"),
        )
        trace_event(
            name="llm_factory_create",
            metadata={
                "provider": "yandex",
                "transport": transport,
                "model": effective_model,
                "temperature": temperature,
                "max_tokens": yandex_kwargs.get("max_tokens"),
            },
        )

        if transport == "openai":
            from app.services.yandex_openai_llm import create_yandex_chat_openai_llm

            # reasoning_mode маппится в reasoning_effort внутри create_yandex_chat_openai_llm
            timeout_oai = llm_kwargs.get("timeout")
            if timeout_oai is not None:
                yandex_kwargs["timeout"] = timeout_oai
            llm = create_yandex_chat_openai_llm(
                model=effective_model,
                temperature=temperature,
                **yandex_kwargs,
            )
        else:
            from app.services.yandex_llm import ChatYandexGPT as AppChatYandexGPT

            llm = AppChatYandexGPT(
                model=effective_model,
                temperature=temperature,
                **yandex_kwargs,
            )

        if use_rate_limiting and config.RATE_LIMIT_ENABLED:
            try:
                from app.services.rate_limiter import (
                    RateLimitedLLMWrapper,
                    get_rate_limiter,
                    get_llm_semaphore,
                )

                llm = RateLimitedLLMWrapper(
                    llm=llm,
                    rate_limiter=get_rate_limiter(),
                    semaphore=get_llm_semaphore(),
                )
                logger.info("Using Yandex LLM with rate limiting")
            except ImportError as rate_error:
                logger.warning("Rate limiting not available: %s", rate_error)
        else:
            logger.info("Using Yandex LLM without rate limiting")

        if cache_enabled:
            with _llm_cache_lock:
                if len(_llm_cache) < 64:
                    _llm_cache[cache_key] = llm
        return _attach_langfuse_llm_instrumentation(llm)

    if provider == "ollama":
        from langchain_openai import ChatOpenAI

        effective_model = (model or config.OLLAMA_MODEL or "gemma4").strip()
        base_url = (config.OLLAMA_BASE_URL or "http://localhost:11434/v1").strip()
        api_key = (config.OLLAMA_API_KEY or "ollama").strip()

        ollama_kwargs = dict(llm_kwargs)
        reasoning_mode = ollama_kwargs.pop("reasoning_mode", None)
        model_kwargs = dict(ollama_kwargs.pop("model_kwargs", {}) or {})
        if reasoning_mode:
            model_kwargs["reasoning_mode"] = reasoning_mode
        if model_kwargs:
            ollama_kwargs["model_kwargs"] = model_kwargs

        logger.info(
            "Creating Ollama LLM: model=%s base_url=%s temperature=%s",
            effective_model,
            base_url,
            temperature,
        )
        trace_event(
            name="llm_factory_create",
            metadata={
                "provider": "ollama",
                "model": effective_model,
                "temperature": temperature,
            },
        )
        llm = ChatOpenAI(
            model=effective_model,
            openai_api_base=base_url,
            openai_api_key=api_key,
            temperature=temperature,
            **ollama_kwargs,
        )

        if use_rate_limiting and config.RATE_LIMIT_ENABLED:
            try:
                from app.services.rate_limiter import (
                    RateLimitedLLMWrapper,
                    get_rate_limiter,
                    get_llm_semaphore,
                )

                llm = RateLimitedLLMWrapper(
                    llm=llm,
                    rate_limiter=get_rate_limiter(),
                    semaphore=get_llm_semaphore(),
                )
                logger.info("Using Ollama LLM with rate limiting")
            except ImportError as rate_error:
                logger.warning("Rate limiting not available: %s", rate_error)
        else:
            logger.info("Using Ollama LLM without rate limiting")

        if cache_enabled:
            with _llm_cache_lock:
                if len(_llm_cache) < 64:
                    _llm_cache[cache_key] = llm
        return _attach_langfuse_llm_instrumentation(llm)

    raise ValueError(
        f"Unknown LLM provider: {provider}. "
        "Supported: 'yandex', 'gigachat', 'ollama'."
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


def user_facing_llm_reasoning_kwargs(*, mode: str = "normal") -> Dict[str, Any]:
    """
    Provider kwargs so user-visible text is emitted in AIMessage.content.

    Yandex DeepSeek may stream internal reasoning in additional_kwargs; for
    case-assistant answers (normal/garant/draft) we disable it so streaming
    collectors reading ``content`` receive the final answer.
    """
    if (mode or "").strip().lower() == "deep_think":
        return {}
    return {"reasoning_mode": "disabled"}


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

