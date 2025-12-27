"""Configuration for Legal AI Vault Backend"""
import os
import logging
from typing import List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Application configuration"""
    
    # OpenRouter (совместим с OpenAI API)
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL: str = os.getenv("OPENROUTER_MODEL", "openrouter/auto")
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql://user:password@localhost:5432/legal_ai_vault"
    )
    
    # Vector Store: Only pgvector is supported
    # VECTOR_STORE_TYPE removed - using pgvector only
    
    # CORS
    CORS_ORIGINS: List[str] = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:5174"
    ).split(",")
    
    # API Settings
    API_TITLE: str = "Legal AI Vault MVP"
    API_VERSION: str = "0.1.0"
    
    # File Upload
    MAX_FILE_SIZE: int = 5 * 1024 * 1024  # 5 MB
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".docx", ".txt", ".xlsx"]
    MAX_TOTAL_TEXT_CHARS: int = 2_000_000  # Ограничение суммарного текста

    # OpenRouter / LLM context limits
    MAX_CONTEXT_CHARS: int = 60_000  # Приближённо к лимиту ~32k токенов
    
    # Multi-Agent System Settings
    AGENT_ENABLED: bool = os.getenv("AGENT_ENABLED", "true").lower() == "true"
    AGENT_MAX_PARALLEL: int = int(os.getenv("AGENT_MAX_PARALLEL", "3"))  # Max parallel agents
    AGENT_TIMEOUT: int = int(os.getenv("AGENT_TIMEOUT", "300"))  # Timeout per agent in seconds
    AGENT_RETRY_COUNT: int = int(os.getenv("AGENT_RETRY_COUNT", "2"))  # Retry count on failure
    
    # Yandex Cloud AI Studio (GPT + Embeddings + Vector Store)
    YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")
    YANDEX_IAM_TOKEN: str = os.getenv("YANDEX_IAM_TOKEN", "")  # Альтернатива API ключу
    YANDEX_FOLDER_ID: str = os.getenv("YANDEX_FOLDER_ID", "")  # Обязательно для работы Yandex сервисов
    YANDEX_GPT_MODEL: str = os.getenv("YANDEX_GPT_MODEL", "yandexgpt-lite/latest")  # Модель по умолчанию
    YANDEX_EMBEDDING_MODEL: str = os.getenv("YANDEX_EMBEDDING_MODEL", "text-search-query/latest")  # Модель embeddings по умолчанию
    
    # Полные URI моделей (приоритет над короткими именами)
    # Формат: gpt://<folder-id>/yandexgpt-lite/latest или emb://<folder-id>/text-search-query/latest
    YANDEX_GPT_MODEL_URI: str = os.getenv("YANDEX_GPT_MODEL_URI", "")
    YANDEX_EMBEDDING_MODEL_URI: str = os.getenv("YANDEX_EMBEDDING_MODEL_URI", "")
    
    # GigaChat (Сбер) - с поддержкой function calling
    GIGACHAT_CREDENTIALS: str = os.getenv("GIGACHAT_CREDENTIALS", "")
    GIGACHAT_MODEL: str = os.getenv("GIGACHAT_MODEL", "GigaChat")
    GIGACHAT_VERIFY_SSL: bool = os.getenv("GIGACHAT_VERIFY_SSL", "true").lower() == "true"
    
    # Выбор LLM провайдера для агентов (yandex или gigachat)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "yandex")  # "yandex" или "gigachat"
    # Yandex Index prefix - removed (Yandex Vector Store no longer used)
    # YANDEX_INDEX_PREFIX: str = os.getenv("YANDEX_INDEX_PREFIX", "legal_ai_vault")
    
    # LangSmith (LangChain monitoring and compliance)
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "legal-ai-vault")
    LANGSMITH_TRACING: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGSMITH_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    
    # File Storage
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    
    # Security / JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", os.getenv("SECRET_KEY", "your-secret-key-change-in-production"))
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ALGORITHM: str = "HS256"  # Alias for JWT_ALGORITHM
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours


# Create config instance
config = Config()
