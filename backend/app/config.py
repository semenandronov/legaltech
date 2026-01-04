"""Configuration for Legal AI Vault Backend"""
import os
import logging
from typing import List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Application configuration"""
    
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

    # LLM context limits
    MAX_CONTEXT_CHARS: int = 60_000  # Приближённо к лимиту ~32k токенов
    
    # RAG Settings
    RAG_USE_RERANKER: bool = os.getenv("RAG_USE_RERANKER", "false").lower() == "true"  # Use cross-encoder reranker for relevance scoring
    RAG_MIN_RELEVANCE_SCORE: float = float(os.getenv("RAG_MIN_RELEVANCE_SCORE", "0.5"))  # Minimum relevance score threshold
    RAG_LLM_EVALUATION_ENABLED: bool = os.getenv("RAG_LLM_EVALUATION_ENABLED", "true").lower() == "true"  # Enable LLM-based relevance evaluation
    RAG_REQUIRE_SOURCES: bool = os.getenv("RAG_REQUIRE_SOURCES", "true").lower() == "true"  # Require source citations in answers
    RAG_ALLOW_UNCERTAINTY: bool = os.getenv("RAG_ALLOW_UNCERTAINTY", "true").lower() == "true"  # Allow model to express uncertainty when information is insufficient
    
    # Multi-Agent System Settings
    AGENT_ENABLED: bool = os.getenv("AGENT_ENABLED", "true").lower() == "true"
    AGENT_MAX_PARALLEL: int = int(os.getenv("AGENT_MAX_PARALLEL", "5"))  # Max parallel agents (increased from 3)
    AGENT_TIMEOUT: int = int(os.getenv("AGENT_TIMEOUT", "120"))  # Default timeout per agent in seconds (reduced from 300)
    AGENT_RETRY_COUNT: int = int(os.getenv("AGENT_RETRY_COUNT", "2"))  # Retry count on failure
    
    # Human-in-the-loop Settings
    HUMAN_FEEDBACK_TIMEOUT: int = int(os.getenv("HUMAN_FEEDBACK_TIMEOUT", "300"))  # Timeout for human feedback in seconds (default: 5 minutes)
    HUMAN_FEEDBACK_MAX_ATTEMPTS: int = int(os.getenv("HUMAN_FEEDBACK_MAX_ATTEMPTS", "3"))  # Maximum attempts before skipping
    HUMAN_FEEDBACK_FALLBACK_STRATEGY: str = os.getenv("HUMAN_FEEDBACK_FALLBACK_STRATEGY", "skip")  # Fallback strategy: "skip", "retry", "abort"
    
    # Yandex Cloud AI Studio (GPT + Embeddings + Vector Store)
    YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")
    YANDEX_IAM_TOKEN: str = os.getenv("YANDEX_IAM_TOKEN", "")  # Альтернатива API ключу
    YANDEX_FOLDER_ID: str = os.getenv("YANDEX_FOLDER_ID", "")  # Обязательно для работы Yandex сервисов
    YANDEX_GPT_MODEL: str = os.getenv("YANDEX_GPT_MODEL", "yandexgpt-lite/latest")  # Модель по умолчанию
    YANDEX_EMBEDDING_MODEL: str = os.getenv("YANDEX_EMBEDDING_MODEL", "text-search-query/latest")  # Модель embeddings по умолчанию
    YANDEX_AI_STUDIO_CLASSIFIER_ID: str = os.getenv("YANDEX_AI_STUDIO_CLASSIFIER_ID", "")  # ID классификатора в Yandex AI Studio
    
    # Полные URI моделей (приоритет над короткими именами)
    # Формат: gpt://<folder-id>/yandexgpt-lite/latest или emb://<folder-id>/text-search-query/latest
    YANDEX_GPT_MODEL_URI: str = os.getenv("YANDEX_GPT_MODEL_URI", "")
    YANDEX_EMBEDDING_MODEL_URI: str = os.getenv("YANDEX_EMBEDDING_MODEL_URI", "")
    
    # GigaChat (Сбер) - с поддержкой function calling
    GIGACHAT_CREDENTIALS: str = os.getenv("GIGACHAT_CREDENTIALS", "")  # Authorization Key (base64 encoded ClientID:ClientSecret)
    GIGACHAT_MODEL: str = os.getenv("GIGACHAT_MODEL", "GigaChat")
    # По умолчанию отключаем проверку SSL для совместимости с некоторыми окружениями (Render, прокси)
    # Установите GIGACHAT_VERIFY_SSL=true для включения проверки SSL (более безопасно)
    GIGACHAT_VERIFY_SSL: bool = os.getenv("GIGACHAT_VERIFY_SSL", "false").lower() == "true"
    GIGACHAT_SCOPE: str = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")  # Scope для получения токена (GIGACHAT_API_PERS для физических лиц)
    
    # Выбор LLM провайдера для агентов (только gigachat)
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gigachat")  # "gigachat"
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
