"""Factory for creating LLM instances (YandexGPT or GigaChat)"""
from typing import Optional
from app.config import config
import logging

logger = logging.getLogger(__name__)


def create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.1,
    **kwargs
):
    """
    Create LLM instance based on provider
    
    Args:
        provider: "yandex" or "gigachat" (default: from config.LLM_PROVIDER)
        model: Model name (optional)
        temperature: Temperature for generation
        **kwargs: Additional arguments
    
    Returns:
        LLM instance (ChatYandexGPT or GigaChat from langchain-gigachat)
    """
    provider = provider or config.LLM_PROVIDER or "yandex"
    provider = provider.lower()
    
    if provider == "gigachat":
        try:
            # Используем наш кастомный wrapper (совместим с langchain-core 1.2.2)
            # langchain-gigachat требует langchain-core<0.4, что несовместимо с нашими версиями
            from app.services.gigachat_llm import ChatGigaChat
            
            if not config.GIGACHAT_CREDENTIALS:
                logger.warning(
                    "GIGACHAT_CREDENTIALS not set, falling back to YandexGPT. "
                    "Set GIGACHAT_CREDENTIALS in .env file."
                )
                provider = "yandex"
            else:
                logger.info("Using GigaChat LLM via custom wrapper (supports function calling, compatible with langchain-core 1.2.2)")
                return ChatGigaChat(
                    credentials=config.GIGACHAT_CREDENTIALS,
                    model=model or config.GIGACHAT_MODEL,
                    temperature=temperature,
                    verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
                    **kwargs
                )
        except ImportError as e:
            logger.warning(
                f"GigaChat SDK not available ({e}), falling back to YandexGPT. "
                "Install with: pip install gigachat"
            )
            provider = "yandex"
        except Exception as e:
            logger.error(f"Failed to initialize GigaChat: {e}, falling back to YandexGPT")
            provider = "yandex"
    
    # Fallback to YandexGPT
    if provider == "yandex":
        from app.services.yandex_llm import ChatYandexGPT
        logger.info("Using YandexGPT LLM (no function calling support)")
        return ChatYandexGPT(
            model=model,
            temperature=temperature,
            **kwargs
        )
    
    raise ValueError(
        f"Unknown LLM provider: {provider}. "
        "Supported providers: 'yandex', 'gigachat'"
    )

