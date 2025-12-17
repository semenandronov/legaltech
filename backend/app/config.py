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
    
    # LangSmith Settings (optional, for monitoring and debugging)
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "legal-ai-vault")
    LANGSMITH_TRACING: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGSMITH_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    
    # JWT Settings
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "your-secret-key-change-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours
    
    def __init__(self):
        """Validate configuration on initialization"""
        self._validate()
        self._setup_langsmith()
    
    def _setup_langsmith(self):
        """Setup LangSmith tracing if enabled"""
        if self.LANGSMITH_TRACING and self.LANGSMITH_API_KEY:
            import os
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ["LANGCHAIN_API_KEY"] = self.LANGSMITH_API_KEY
            os.environ["LANGCHAIN_PROJECT"] = self.LANGSMITH_PROJECT
            os.environ["LANGCHAIN_ENDPOINT"] = self.LANGSMITH_ENDPOINT
            logger.info("✅ LangSmith tracing enabled")
        elif self.LANGSMITH_TRACING and not self.LANGSMITH_API_KEY:
            logger.warning(
                "LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY is not set. "
                "LangSmith tracing will not work."
            )
    
    def _validate(self):
        """Validate critical configuration values"""
        # Validate OpenRouter API key
        if not self.OPENROUTER_API_KEY or self.OPENROUTER_API_KEY.strip() == "":
            logger.warning(
                "OPENROUTER_API_KEY is not set or empty. "
                "LLM features will not work. Please set OPENROUTER_API_KEY in .env file."
            )
        
        # Validate JWT secret key
        default_jwt_secret = "your-secret-key-change-in-production"
        if self.JWT_SECRET_KEY == default_jwt_secret:
            logger.warning(
                "⚠️  SECURITY WARNING: Using default JWT_SECRET_KEY! "
                "This is insecure for production. Please set a strong JWT_SECRET_KEY in .env file."
            )
        elif len(self.JWT_SECRET_KEY) < 32:
            logger.warning(
                f"JWT_SECRET_KEY is too short ({len(self.JWT_SECRET_KEY)} chars). "
                "For security, use at least 32 characters."
            )


config = Config()

