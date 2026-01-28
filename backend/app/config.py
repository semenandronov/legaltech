"""Configuration for Legal AI Vault Backend"""
import os
import logging
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class Config:
    """Application configuration"""
    
    # Database
    _default_db_url = "postgresql://user:password@localhost:5432/legal_ai_vault"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        _default_db_url
    )
    
    # Validate DATABASE_URL on initialization
    @staticmethod
    def _validate_database_url():
        """Validate that DATABASE_URL is set and not using default value"""
        db_url = os.getenv("DATABASE_URL", Config._default_db_url)
        
        # Always print to stderr for visibility (works even if logger not configured)
        import sys
        
        if db_url == Config._default_db_url:
            error_msg = (
                "\n" + "="*80 + "\n"
                "❌ КРИТИЧЕСКАЯ ОШИБКА: DATABASE_URL не установлена!\n"
                "="*80 + "\n"
                "Приложение пытается использовать значение по умолчанию: localhost:5432\n"
                "Это не будет работать в облачном окружении (Timeweb App Platform).\n\n"
                "РЕШЕНИЕ:\n"
                "1. Откройте панель Timeweb Cloud\n"
                "2. Перейдите в App Platform -> Ваше приложение\n"
                "3. Откройте раздел 'Переменные окружения'\n"
                "4. Добавьте переменную:\n"
                "   Имя: DATABASE_URL\n"
                "   Значение: postgresql://user:password@host:port/database\n"
                "5. Сохраните изменения (приложение перезапустится автоматически)\n"
                "="*80 + "\n"
            )
            print(error_msg, file=sys.stderr)
            try:
                logger.error(error_msg)
            except:
                pass  # Logger may not be configured yet
            raise ValueError("DATABASE_URL не установлена. Установите переменную окружения DATABASE_URL в настройках приложения.")
        
        # Try to extract connection string from psql command if present
        import re
        if db_url.strip().startswith("psql"):
            # Try to extract postgresql:// URL from psql command
            # Pattern: psql 'postgresql://...' or psql "postgresql://..."
            match = re.search(r"['\"](postgresql://[^'\"]+)['\"]", db_url)
            if match:
                extracted_url = match.group(1)
                warning_msg = (
                    f"\n⚠️  Обнаружена команда psql в DATABASE_URL. Извлечена строка подключения.\n"
                    f"Рекомендуется использовать только строку подключения без команды psql.\n"
                    f"Используется: {extracted_url[:50]}...\n"
                )
                print(warning_msg, file=sys.stderr)
                try:
                    logger.warning(warning_msg)
                except:
                    pass
                db_url = extracted_url
            else:
                # Try to find postgresql:// anywhere in the string
                match = re.search(r"(postgresql://[^\s'\"]+)", db_url)
                if match:
                    extracted_url = match.group(1)
                    warning_msg = (
                        f"\n⚠️  Обнаружена команда psql в DATABASE_URL. Извлечена строка подключения.\n"
                        f"Рекомендуется использовать только строку подключения без команды psql.\n"
                        f"Используется: {extracted_url[:50]}...\n"
                    )
                    print(warning_msg, file=sys.stderr)
                    try:
                        logger.warning(warning_msg)
                    except:
                        pass
                    db_url = extracted_url
        
        # Validate DATABASE_URL format (must start with postgresql:// or postgres://)
        if not (db_url.startswith("postgresql://") or db_url.startswith("postgres://")):
            error_msg = (
                "\n" + "="*80 + "\n"
                "❌ КРИТИЧЕСКАЯ ОШИБКА: Неверный формат DATABASE_URL!\n"
                "="*80 + "\n"
                f"Текущее значение: {db_url[:100]}...\n\n"
                "DATABASE_URL должна быть строкой подключения к PostgreSQL в формате:\n"
                "postgresql://user:password@host:port/database\n\n"
                "ПРИМЕРЫ:\n"
                "postgresql://myuser:mypassword@db.example.com:5432/mydatabase\n"
                "postgresql://user:pass@localhost:5432/dbname\n\n"
                "ВНИМАНИЕ:\n"
                "- Если вы скопировали команду psql, используйте только строку подключения внутри кавычек\n"
                "- Убедитесь, что вы не перепутали DATABASE_URL с другими переменными:\n"
                "  - DATABASE_URL - строка подключения к PostgreSQL\n"
                "  - YANDEX_API_KEY - API ключ Yandex Cloud\n"
                "  - GIGACHAT_CREDENTIALS - учетные данные GigaChat\n\n"
                "РЕШЕНИЕ:\n"
                "1. Откройте панель Timeweb Cloud\n"
                "2. Перейдите в App Platform -> Ваше приложение\n"
                "3. Откройте раздел 'Переменные окружения'\n"
                "4. Найдите переменную DATABASE_URL\n"
                "5. Если значение содержит команду 'psql', извлеките только строку подключения:\n"
                "   Было: psql 'postgresql://user:pass@host:port/db'\n"
                "   Должно быть: postgresql://user:pass@host:port/db\n"
                "6. Убедитесь, что значение начинается с 'postgresql://'\n"
                "="*80 + "\n"
            )
            print(error_msg, file=sys.stderr)
            try:
                logger.error(error_msg)
            except:
                pass
            raise ValueError(f"Неверный формат DATABASE_URL. Ожидается строка вида 'postgresql://user:password@host:port/database', получено: {db_url[:100]}...")
        
        # Update DATABASE_URL if it was extracted from psql command
        if db_url != os.getenv("DATABASE_URL", Config._default_db_url):
            Config.DATABASE_URL = db_url
        
        # Check for localhost in production
        is_production = os.getenv("ENVIRONMENT", "").lower() == "production" or os.getenv("PORT") is not None
        if is_production and ("localhost" in db_url or "127.0.0.1" in db_url):
            warning_msg = (
                f"\n⚠️  ПРЕДУПРЕЖДЕНИЕ: DATABASE_URL содержит localhost/127.0.0.1\n"
                f"Это может не работать в облачном окружении.\n"
                f"URL (без пароля): {db_url.split('@')[0] if '@' in db_url else db_url[:50]}@***\n"
            )
            print(warning_msg, file=sys.stderr)
            try:
                logger.warning(warning_msg)
            except:
                pass
        
        # Log success (mask password)
        url_parts = db_url.split("@")
        if len(url_parts) > 1:
            success_msg = f"✅ DATABASE_URL установлена: {url_parts[0]}@***"
        else:
            success_msg = f"✅ DATABASE_URL установлена: {db_url[:50]}..."
        print(success_msg, file=sys.stderr)
        try:
            logger.info(success_msg)
        except:
            pass
    
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
    
    # Structured RAG Output Settings
    RAG_USE_STRUCTURED_OUTPUT: bool = os.getenv("RAG_USE_STRUCTURED_OUTPUT", "true").lower() == "true"  # Use structured JSON output with mandatory citations
    RAG_MANDATORY_CITATIONS: bool = os.getenv("RAG_MANDATORY_CITATIONS", "true").lower() == "true"  # Require citations for all claims (enforced by schema)
    RAG_MIN_CITATION_LENGTH: int = int(os.getenv("RAG_MIN_CITATION_LENGTH", "10"))  # Minimum quote length in characters
    RAG_CITATION_VERIFICATION_IN_PIPELINE: bool = os.getenv("RAG_CITATION_VERIFICATION_IN_PIPELINE", "false").lower() == "true"  # Verify citations with LLM-as-Judge in pipeline
    
    # Citation System Settings (Phase 2, 3, 5)
    CITATION_FIRST_ENABLED: bool = os.getenv("CITATION_FIRST_ENABLED", "true").lower() == "true"  # Enable citation-first generation
    CITATION_VERIFICATION_ENABLED: bool = os.getenv("CITATION_VERIFICATION_ENABLED", "true").lower() == "true"  # Enable extended citation verification
    CITATION_LLM_JUDGE_ENABLED: bool = os.getenv("CITATION_LLM_JUDGE_ENABLED", "true").lower() == "true"  # Use LLM-as-judge for verification
    CITATION_MIN_INDEPENDENT_SOURCES: int = int(os.getenv("CITATION_MIN_INDEPENDENT_SOURCES", "1"))  # Minimum independent sources for verified claim
    CITATION_CHAR_OFFSETS_ENABLED: bool = os.getenv("CITATION_CHAR_OFFSETS_ENABLED", "true").lower() == "true"  # Save char offsets for new documents
    
    # Multi-Agent System Settings
    AGENT_ENABLED: bool = os.getenv("AGENT_ENABLED", "true").lower() == "true"
    AGENT_MAX_PARALLEL: int = int(os.getenv("AGENT_MAX_PARALLEL", "5"))  # Max parallel agents (increased from 3)
    AGENT_TIMEOUT: int = int(os.getenv("AGENT_TIMEOUT", "60"))  # Default timeout per agent in seconds (optimized for faster responses)
    AGENT_RETRY_COUNT: int = int(os.getenv("AGENT_RETRY_COUNT", "2"))  # Retry count on failure
    
    # Rate Limiting Settings (Phase 4.1)
    RATE_LIMIT_RPS: float = float(os.getenv("RATE_LIMIT_RPS", "2.0"))  # Requests per second to LLM
    RATE_LIMIT_MAX_BUCKET_SIZE: int = int(os.getenv("RATE_LIMIT_MAX_BUCKET_SIZE", "10"))  # Max burst size
    RATE_LIMIT_CHECK_INTERVAL: float = float(os.getenv("RATE_LIMIT_CHECK_INTERVAL", "0.1"))  # Check interval in seconds
    MAX_PARALLEL_LLM_CALLS: int = int(os.getenv("MAX_PARALLEL_LLM_CALLS", "8"))  # Max concurrent LLM calls
    RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"  # Enable rate limiting
    
    # Cache Settings (Phase 1.2)
    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))  # Default cache TTL (1 hour)
    CACHE_SEMANTIC_ENABLED: bool = os.getenv("CACHE_SEMANTIC_ENABLED", "false").lower() == "true"  # Enable semantic cache
    CACHE_SIMILARITY_THRESHOLD: float = float(os.getenv("CACHE_SIMILARITY_THRESHOLD", "0.85"))  # Similarity threshold for semantic cache
    CACHE_CLEANUP_INTERVAL: int = int(os.getenv("CACHE_CLEANUP_INTERVAL", "3600"))  # How often to clean expired cache (seconds)
    
    # Human-in-the-loop Settings
    HUMAN_FEEDBACK_TIMEOUT: int = int(os.getenv("HUMAN_FEEDBACK_TIMEOUT", "300"))  # Timeout for human feedback in seconds (default: 5 minutes)
    HUMAN_FEEDBACK_MAX_ATTEMPTS: int = int(os.getenv("HUMAN_FEEDBACK_MAX_ATTEMPTS", "3"))  # Maximum attempts before skipping
    HUMAN_FEEDBACK_FALLBACK_STRATEGY: str = os.getenv("HUMAN_FEEDBACK_FALLBACK_STRATEGY", "skip")  # Fallback strategy: "skip", "retry", "abort"
    
    # LLM Temperature Settings (CRITICAL for legal determinism)
    LLM_TEMPERATURE_LEGAL: float = float(os.getenv("LLM_TEMPERATURE_LEGAL", "0.0"))  # ZERO for legal answers (deterministic)
    LLM_TEMPERATURE_VERIFIER: float = float(os.getenv("LLM_TEMPERATURE_VERIFIER", "0.0"))  # ZERO for citation verification
    LLM_TEMPERATURE_JUDGE: float = float(os.getenv("LLM_TEMPERATURE_JUDGE", "0.0"))  # ZERO for LLM-as-judge
    LLM_TEMPERATURE_CREATIVE: float = float(os.getenv("LLM_TEMPERATURE_CREATIVE", "0.3"))  # Higher temperature for creative tasks
    
    # Yandex Cloud AI Studio (GPT + Embeddings + Vector Store)
    YANDEX_API_KEY: str = os.getenv("YANDEX_API_KEY", "")
    YANDEX_IAM_TOKEN: str = os.getenv("YANDEX_IAM_TOKEN", "")
    
    # Garant API
    GARANT_API_KEY: str = os.getenv("GARANT_API_KEY", "")
    GARANT_API_URL: str = os.getenv("GARANT_API_URL", "https://api.garant.ru/v2")  # Альтернатива API ключу
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
    
    # GigaChat Model Selection (Lite/Pro)
    GIGACHAT_LITE_MODEL: str = os.getenv("GIGACHAT_LITE_MODEL", "GigaChat-Lite")
    GIGACHAT_PRO_MODEL: str = os.getenv("GIGACHAT_PRO_MODEL", "GigaChat-Pro")
    MODEL_SELECTION_ENABLED: bool = os.getenv("MODEL_SELECTION_ENABLED", "true").lower() == "true"
    
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
    
    # Redis for Caching and Presence (Phase 4.1)
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    PRESENCE_TTL_SECONDS: int = int(os.getenv("PRESENCE_TTL_SECONDS", "60"))  # TTL for user presence in seconds
    
    # LangGraph Postgres Checkpointer Pool Settings
    LANGGRAPH_POSTGRES_POOL_MAX_SIZE: int = int(os.getenv("LANGGRAPH_POSTGRES_POOL_MAX_SIZE", "20"))  # Max connections in pool


# Create config instance
config = Config()

# Validate DATABASE_URL on module import
try:
    Config._validate_database_url()
except ValueError as e:
    # In production, we want to fail fast if DATABASE_URL is not set
    import sys
    print(str(e), file=sys.stderr)
    sys.exit(1)
