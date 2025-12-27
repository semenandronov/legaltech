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
        LLM instance (ChatYandexGPT or ChatGigaChat)
    """
    provider = provider or config.LLM_PROVIDER or "yandex"
    provider = provider.lower()
    
    if provider == "gigachat":
        try:
            from app.services.gigachat_llm import ChatGigaChat
            
            if not config.GIGACHAT_CREDENTIALS:
                logger.warning(
                    "GIGACHAT_CREDENTIALS not set, falling back to YandexGPT. "
                    "Set GIGACHAT_CREDENTIALS in .env file."
                )
                provider = "yandex"
            else:
                logger.info("Using GigaChat LLM (supports function calling)")
                return ChatGigaChat(
                    credentials=config.GIGACHAT_CREDENTIALS,
                    model=model or config.GIGACHAT_MODEL,
                    temperature=temperature,
                    verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
                    **kwargs
                )
        except ImportError as e:
            logger.warning(f"GigaChat not available ({e}), falling back to YandexGPT")
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

