"""Factory for creating LLM instances (GigaChat only)"""
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
    Create LLM instance (GigaChat only)
    
    Args:
        provider: "gigachat" (default: from config.LLM_PROVIDER)
        model: Model name (optional)
        temperature: Temperature for generation
        **kwargs: Additional arguments
    
    Returns:
        LLM instance (ChatGigaChat)
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
            
            logger.info("Using GigaChat LLM via custom wrapper (supports function calling, compatible with langchain-core 1.2.2)")
            return ChatGigaChat(
                credentials=config.GIGACHAT_CREDENTIALS,
                model=model or config.GIGACHAT_MODEL,
                temperature=temperature,
                verify_ssl_certs=config.GIGACHAT_VERIFY_SSL,
                **kwargs
            )
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

