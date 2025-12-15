"""Configuration for Legal AI Vault Backend"""
import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


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


config = Config()

