"""Configuration for Legal AI Vault Backend"""
import os
import logging
import sys
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# #region agent log
def _debug_log(location, message, data, hypothesis_id="A", run_id="startup"):
    """Write debug log to stderr (Docker captures) and /tmp/debug.log"""
    log_entry = json.dumps({
        "sessionId": "debug-session",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now().timestamp() * 1000)
    })
    try:
        print(f"[DEBUG] {log_entry}", file=sys.stderr, flush=True)
        with open('/tmp/debug.log', 'a') as f:
            f.write(log_entry + '\n')
    except: pass

try:
    _debug_log("config.py:1", "Config module import started", {"step": "config_import_start"})
except: pass
# #endregion

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()  # CWD (например backend/.env) переопределяет корень

# #region agent log
try:
    _debug_log("config.py:load_dotenv", "After load_dotenv", {"step": "after_load_dotenv", "db_url_set": bool(os.getenv("DATABASE_URL"))})
except: pass
# #endregion

logger = logging.getLogger(__name__)


def clean_env_str(value: Optional[str], default: str = "") -> str:
    """Убирает пробелы и обрамляющие кавычки (Docker --env-file передаёт их буквально)."""
    if value is None:
        return default
    cleaned = value.strip().strip('"').strip("'")
    return cleaned if cleaned else default


def redact_database_url(url: str) -> str:
    """Маскирует пароль (и при необходимости user) в DSN для логов и исключений."""
    if not url or not isinstance(url, str):
        return "postgresql://***"
    try:
        from urllib.parse import urlparse, urlunparse

        raw = url.strip()
        p = urlparse(raw)
        if not p.scheme or not str(p.scheme).lower().startswith("postgres"):
            return "***"
        user = p.username or ""
        host = p.hostname or ""
        port = f":{p.port}" if p.port else ""
        auth = f"{user}:***@" if user else ""
        netloc = f"{auth}{host}{port}"
        return urlunparse((p.scheme, netloc, p.path or "", "", "", ""))
    except Exception:
        return "postgresql://***"


class Config:
    """Application configuration"""
    
    # Database
    _default_db_url = "postgresql://user:password@localhost:5432/legal_ai_vault"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        _default_db_url
    )

    # SQLAlchemy QueuePool (увеличить при SSE + параллельных запросах)
    SQLALCHEMY_POOL_SIZE: int = int(os.getenv("SQLALCHEMY_POOL_SIZE", "10"))
    SQLALCHEMY_MAX_OVERFLOW: int = int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "20"))
    SQLALCHEMY_POOL_TIMEOUT: int = int(os.getenv("SQLALCHEMY_POOL_TIMEOUT", "60"))

    # Зависшие файлы (pending/processing) при init_db / старте приложения.
    # В serverless новый контейнер не должен помечать error файлы, которые ещё обрабатывает другой инстанс.
    # Варианты: RESET_STUCK_FILES_ON_STARTUP=false или STUCK_FILE_RESET_MIN_AGE_MINUTES=45 (только «устаревшие»).
    RESET_STUCK_FILES_ON_STARTUP: bool = (
        os.getenv("RESET_STUCK_FILES_ON_STARTUP", "true").strip().lower() in ("1", "true", "yes")
    )
    STUCK_FILE_RESET_MIN_AGE_MINUTES: int = int(
        (os.getenv("STUCK_FILE_RESET_MIN_AGE_MINUTES", "0") or "0").strip().strip('"').strip("'")
    )

    # API / Worker (два Yandex Serverless Containers из одного Docker-образа)
    # api — сайт и REST; worker — только POST /internal/process-files
    APP_ROLE: str = (os.getenv("APP_ROLE", "api") or "api").strip().lower()
    WORKER_BASE_URL: str = (os.getenv("WORKER_BASE_URL") or "").strip().rstrip("/")
    INTERNAL_WORKER_SECRET: str = (os.getenv("INTERNAL_WORKER_SECRET") or "").strip()
    # auto: worker при заданных WORKER_BASE_URL + INTERNAL_WORKER_SECRET; local | worker — принудительно
    FILE_PROCESSING_MODE: str = (
        (os.getenv("FILE_PROCESSING_MODE", "auto") or "auto").strip().lower()
    )
    WORKER_DISPATCH_TIMEOUT_SEC: float = float(
        os.getenv("WORKER_DISPATCH_TIMEOUT_SEC", "30") or "30"
    )
    # Bearer для вызова worker (Yandex 403 без токена при invoker на SA)
    WORKER_DISPATCH_USE_METADATA_IAM: bool = (
        os.getenv("WORKER_DISPATCH_USE_METADATA_IAM", "true").strip().lower()
        in ("1", "true", "yes")
    )

    def is_worker_role(self) -> bool:
        return self.APP_ROLE == "worker"

    def file_processing_via_worker(self) -> bool:
        """API шлёт обработку на worker; сам worker никогда не диспатчит наружу."""
        if self.is_worker_role():
            return False
        mode = self.FILE_PROCESSING_MODE
        configured = bool(self.WORKER_BASE_URL and self.INTERNAL_WORKER_SECRET)
        if mode == "local":
            return False
        if mode == "worker":
            return configured
        return configured  # auto

    # Параллельная обработка файлов в одном batch (worker/API local).
    # OCR pacing — в yandex_vision_ocr (квота ~10 async start/s); здесь — файлы / LLM / embed.
    FILE_PROCESSING_MAX_PARALLEL_FILES: int = int(
        os.getenv("FILE_PROCESSING_MAX_PARALLEL_FILES", "4") or "4"
    )
    FILE_PROCESSING_MAX_PARALLEL_PASSPORT: int = int(
        os.getenv("FILE_PROCESSING_MAX_PARALLEL_PASSPORT", "3") or "3"
    )
    FILE_PROCESSING_MAX_PARALLEL_EMBEDDINGS: int = int(
        os.getenv("FILE_PROCESSING_MAX_PARALLEL_EMBEDDINGS", "2") or "2"
    )
    # Docling layout/table inference (MPS/GPU): serialize to avoid oversubscription.
    FILE_PROCESSING_MAX_PARALLEL_DOCLING: int = int(
        os.getenv("FILE_PROCESSING_MAX_PARALLEL_DOCLING", "1") or "1"
    )
    # How many cases may ingest files concurrently (scheduler-level cap).
    FILE_PROCESSING_MAX_CONCURRENT_CASES: int = int(
        os.getenv("FILE_PROCESSING_MAX_CONCURRENT_CASES", "2") or "2"
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
                    f"Используется: {redact_database_url(extracted_url)}\n"
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
                        f"Используется: {redact_database_url(extracted_url)}\n"
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
                f"Текущее значение: {redact_database_url(db_url)}\n\n"
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
            raise ValueError(
                "Неверный формат DATABASE_URL. Ожидается строка вида "
                f"'postgresql://user:password@host:port/database', получено: {redact_database_url(db_url)}"
            )
        
        # Update DATABASE_URL if it was extracted from psql command
        if db_url != os.getenv("DATABASE_URL", Config._default_db_url):
            Config.DATABASE_URL = db_url
        
        # Check for localhost in production
        is_production = os.getenv("ENVIRONMENT", "").lower() == "production" or os.getenv("PORT") is not None
        if is_production and ("localhost" in db_url or "127.0.0.1" in db_url):
            warning_msg = (
                f"\n⚠️  ПРЕДУПРЕЖДЕНИЕ: DATABASE_URL содержит localhost/127.0.0.1\n"
                f"Это может не работать в облачном окружении.\n"
                f"URL: {redact_database_url(db_url)}\n"
            )
            print(warning_msg, file=sys.stderr)
            try:
                logger.warning(warning_msg)
            except:
                pass
        
        # Log success (никогда не логируем user:password в открытом виде)
        success_msg = f"✅ DATABASE_URL установлена: {redact_database_url(db_url)}"
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
    
    # File Upload (env MAX_FILE_SIZE_MB; default 30. Raise for multi-hundred-page statements.)
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE_MB", "30") or "30") * 1024 * 1024
    # Отдельный лимит для Справочника: кодексы в PDF могут быть тяжелее 30 МБ.
    LEGAL_CORPUS_MAX_FILE_SIZE: int = int(
        os.getenv("LEGAL_CORPUS_MAX_FILE_SIZE_MB", "50") or "50"
    ) * 1024 * 1024
    ALLOWED_EXTENSIONS: List[str] = [
        ".pdf",
        ".docx",
        ".html",
        ".htm",
        ".txt",
        ".html",
        ".htm",
        ".xlsx",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".gif",
    ]
    MAX_TOTAL_TEXT_CHARS: int = 2_000_000  # Ограничение суммарного текста

    # Старый batchAnalyze: чанк до N страниц. Новый recognizeTextAsync: см. YANDEX_OCR_ASYNC_MAX_PAGES_PER_REQUEST.
    YANDEX_VISION_MAX_PDF_PAGES: int = int(os.getenv("YANDEX_VISION_MAX_PDF_PAGES", "300"))
    # Новый OCR API: до 200 стр. в одном recognizeTextAsync (см. Vision OCR limits); чанки только если > лимита или >9 МБ.
    YANDEX_OCR_ASYNC_MAX_PAGES_PER_REQUEST: int = int(
        os.getenv("YANDEX_OCR_ASYNC_MAX_PAGES_PER_REQUEST", "200")
    )
    # Новый OCR API: для PDF — только model=page (официальный гайд Yandex recognizeTextAsync).
    YANDEX_OCR_SCAN_MODEL: str = clean_env_str(os.getenv("YANDEX_OCR_SCAN_MODEL"), "page").lower()
    YANDEX_OCR_TABLE_MODEL: str = clean_env_str(os.getenv("YANDEX_OCR_TABLE_MODEL"), "page").lower()
    YANDEX_OCR_PDF_ASYNC_MODEL: str = clean_env_str(
        os.getenv("YANDEX_OCR_PDF_ASYNC_MODEL"), "page"
    ).lower()
    YANDEX_OCR_ASYNC_INITIAL_POLL_DELAY_SEC: float = float(
        os.getenv("YANDEX_OCR_ASYNC_INITIAL_POLL_DELAY_SEC", "2.0") or "2.0"
    )
    # Параллельный OCR только при нескольких чанках (по умолчанию один запрос на весь PDF)
    YANDEX_OCR_ASYNC_PARALLEL_ENABLED: bool = (
        clean_env_str(os.getenv("YANDEX_OCR_ASYNC_PARALLEL_ENABLED"), "false").lower() == "true"
    )
    YANDEX_OCR_ASYNC_MAX_PARALLEL_CHUNKS: int = int(
        os.getenv("YANDEX_OCR_ASYNC_MAX_PARALLEL_CHUNKS", "5")
    )
    # Мин. интервал между стартами async OCR (~8/с при 0.12; квота сервиса 10/с)
    YANDEX_OCR_MIN_START_INTERVAL_SEC: float = float(
        os.getenv("YANDEX_OCR_MIN_START_INTERVAL_SEC", "0.12")
    )
    # Мин. интервал между poll-запросами (квота 50/с; 0 = без доп. паузы в poll-цикле)
    YANDEX_OCR_MIN_POLL_INTERVAL_SEC: float = float(
        os.getenv("YANDEX_OCR_MIN_POLL_INTERVAL_SEC", "0.0")
    )
    # PDF: сначала Yandex Vision для всех документов, затем fallback при ошибках
    PDF_OCR_PREFER_YANDEX: bool = clean_env_str(os.getenv("PDF_OCR_PREFER_YANDEX"), "true").lower() == "true"
    # Минимальная эвристика качества OCR-текста из PDF (символов на страницу с текстом)
    PDF_OCR_MIN_EXPECTED_CHARS_PER_PAGE: int = int(
        os.getenv("PDF_OCR_MIN_EXPECTED_CHARS_PER_PAGE", "5")
    )
    # Скан без текстового слоя: локальный fallback — только Tesseract (PyMuPDF+pytesseract).
    # Основной OCR для сканов — Yandex Vision; текст идёт в LegalChunkerV2 без повторного Docling.
    PDF_SCAN_OCR_ENGINE: str = clean_env_str(os.getenv("PDF_SCAN_OCR_ENGINE"), "tesseract").lower()
    # OCR robust settings (quota/backoff/diagnostics)
    YANDEX_OCR_MAX_RETRIES: int = int(os.getenv("YANDEX_OCR_MAX_RETRIES", "3"))
    YANDEX_OCR_MIN_REQUEST_INTERVAL_SEC: float = float(
        os.getenv("YANDEX_OCR_MIN_REQUEST_INTERVAL_SEC", "1.1")
    )
    YANDEX_OCR_LANGUAGE_CODES: str = os.getenv("YANDEX_OCR_LANGUAGE_CODES", "ru,en")
    # Timeout (seconds) per chunk for new async OCR API (poll loop budget)
    YANDEX_OCR_ASYNC_TIMEOUT_SEC: int = int(os.getenv("YANDEX_OCR_ASYNC_TIMEOUT_SEC", "300"))
    # HTTP read timeouts for ocr.api.cloud.yandex.net (connect, read) — POST start / GET poll
    YANDEX_OCR_HTTP_START_TIMEOUT_SEC: float = float(
        os.getenv("YANDEX_OCR_HTTP_START_TIMEOUT_SEC", "180") or "180"
    )
    YANDEX_OCR_HTTP_POLL_TIMEOUT_SEC: float = float(
        os.getenv("YANDEX_OCR_HTTP_POLL_TIMEOUT_SEC", "120") or "120"
    )
    YANDEX_OCR_DATA_LOGGING_ENABLED: bool = os.getenv(
        "YANDEX_OCR_DATA_LOGGING_ENABLED", "true"
    ).lower() == "true"

    # XLSX: собрать PDF с таблицами и распознать через Yandex Vision (лимит страниц PDF — чанками)
    XLSX_OCR_VIA_PDF_YANDEX: bool = os.getenv("XLSX_OCR_VIA_PDF_YANDEX", "true").lower() == "true"
    XLSX_PDF_MAX_ROWS_PER_SHEET: int = int(os.getenv("XLSX_PDF_MAX_ROWS_PER_SHEET", "6000"))
    XLSX_PDF_MAX_COLS: int = int(os.getenv("XLSX_PDF_MAX_COLS", "32"))

    # Кто может загружать общий правовой справочник (законы, обзоры) в pgvector; через запятую
    LEGAL_CORPUS_UPLOADER_EMAILS: str = clean_env_str(os.getenv(
        "LEGAL_CORPUS_UPLOADER_EMAILS",
        "semenandronov2004@mail.ru",
    ))
    # Судебная практика (КАД): загрузчики CSV; пусто → те же email, что LEGAL_CORPUS_UPLOADER_EMAILS
    COURT_PRACTICE_UPLOADER_EMAILS: str = clean_env_str(os.getenv("COURT_PRACTICE_UPLOADER_EMAILS", ""))
    GIGACHAT_EMBEDDING_MODEL: str = clean_env_str(
        os.getenv("GIGACHAT_EMBEDDING_MODEL"), "EmbeddingsGigaR"
    )
    GIGACHAT_EMBEDDING_DIM: int = int(os.getenv("GIGACHAT_EMBEDDING_DIM", "2560") or "2560")
    GIGACHAT_EMBEDDING_BATCH_SIZE: int = int(os.getenv("GIGACHAT_EMBEDDING_BATCH_SIZE", "8") or "8")
    GIGACHAT_EMBEDDING_MIN_INTERVAL_SEC: float = float(
        os.getenv("GIGACHAT_EMBEDDING_MIN_INTERVAL_SEC", "0.12") or "0.12"
    )
    COURT_PRACTICE_VECTOR_RECALL_K: int = int(os.getenv("COURT_PRACTICE_VECTOR_RECALL_K", "50") or "50")
    COURT_PRACTICE_FTS_RECALL_K: int = int(os.getenv("COURT_PRACTICE_FTS_RECALL_K", "50") or "50")
    COURT_PRACTICE_RRF_K: int = int(os.getenv("COURT_PRACTICE_RRF_K", "60") or "60")
    COURT_PRACTICE_MAX_CHUNKS_PER_CASE: int = int(
        os.getenv("COURT_PRACTICE_MAX_CHUNKS_PER_CASE", "3") or "3"
    )
    COURT_PRACTICE_FINAL_K: int = int(os.getenv("COURT_PRACTICE_FINAL_K", "7") or "7")
    COURT_PRACTICE_USE_RERANKER: bool = (
        os.getenv("COURT_PRACTICE_USE_RERANKER", "true").strip().lower() in ("1", "true", "yes")
    )
    COURT_PRACTICE_CONTEXT_K: int = int(os.getenv("COURT_PRACTICE_CONTEXT_K", "7") or "7")
    COURT_PRACTICE_MAX_CONTEXT_CHARS: int = int(
        os.getenv("COURT_PRACTICE_MAX_CONTEXT_CHARS", "28000") or "28000"
    )
    # Query planner (FTS multi-query supplement) for court practice
    COURT_PRACTICE_LLM_PLANNER_ENABLED: bool = (
        os.getenv("COURT_PRACTICE_LLM_PLANNER_ENABLED", "true").strip().lower() in ("1", "true", "yes")
    )
    COURT_PRACTICE_LLM_PLANNER_MODEL: str = clean_env_str(os.getenv("COURT_PRACTICE_LLM_PLANNER_MODEL", ""))
    COURT_PRACTICE_QUERY_PLANNER_MAX_QUERIES: int = int(
        os.getenv("COURT_PRACTICE_QUERY_PLANNER_MAX_QUERIES", "6") or "6"
    )
    COURT_PRACTICE_FTS_SUPPLEMENT_K: int = int(
        os.getenv("COURT_PRACTICE_FTS_SUPPLEMENT_K", "10") or "10"
    )
    # Детальные nested spans в Langfuse для court_practice (planner, hybrid, FTS, rerank)
    COURT_PRACTICE_LANGFUSE_DETAILED: bool = (
        os.getenv("COURT_PRACTICE_LANGFUSE_DETAILED", "true").strip().lower() in ("1", "true", "yes")
    )
    # Детальные nested spans в Langfuse для case assistant (router, hybrid funnel, rerank)
    CASE_ASSISTANT_LANGFUSE_DETAILED: bool = (
        os.getenv("CASE_ASSISTANT_LANGFUSE_DETAILED", "true").strip().lower() in ("1", "true", "yes")
    )
    # Пошаговые span'ы orchestrator / session / HTTP (case + global assistant).
    ASSISTANT_PIPELINE_LANGFUSE_DETAILED: bool = (
        os.getenv("ASSISTANT_PIPELINE_LANGFUSE_DETAILED", "true").strip().lower() in ("1", "true", "yes")
    )

    # Chunking budgets (safety limits)
    # budget <= 0 means "no truncation"
    LEGAL_CHUNKING_BUDGET_MAX_TOTAL_CHUNKS: int = int(
        os.getenv("LEGAL_CHUNKING_BUDGET_MAX_TOTAL_CHUNKS", "4000") or "4000"
    )
    # Optional override for GLOBAL_LEGAL_CORPUS indexing (legal reference library)
    # Some deployments quote numeric envs in .env (e.g. "0"). Accept both.
    LEGAL_CORPUS_BUDGET_MAX_TOTAL_CHUNKS: int = int(
        (os.getenv("LEGAL_CORPUS_BUDGET_MAX_TOTAL_CHUNKS", "8000") or "8000").strip().strip('"').strip("'")
        or "8000"
    )
    # Устарело: global/case чат в assistant_chat_v2 не подмешивает справочник по этому флагу — только тумблер в UI.
    # Оставлено для совместимости старых .env; значение читается в config, маршруты его не используют.
    LEGAL_CORPUS_FORCE_ENABLED: bool = os.getenv("LEGAL_CORPUS_FORCE_ENABLED", "false").strip().lower() == "true"
    # Устарело: раньше включало справочник в чате по делу без тумблера; маршруты больше не читают.
    LEGAL_CORPUS_AUTO_USE_IN_CASE_CHAT: bool = os.getenv(
        "LEGAL_CORPUS_AUTO_USE_IN_CASE_CHAT", "false"
    ).strip().lower() == "true"
    # Справочник (GLOBAL_LEGAL_CORPUS): размер пула кандидатов до rerank / дедупа (multi-query + широкий recall).
    LEGAL_CORPUS_RECALL_MAX: int = int(
        (os.getenv("LEGAL_CORPUS_RECALL_MAX", "30") or "30").strip().strip('"').strip("'") or "30"
    )
    # Сколько чанков отдавать в промпт после rerank (если не переопределено аргументом k).
    LEGAL_CORPUS_FINAL_K: int = int(
        (os.getenv("LEGAL_CORPUS_FINAL_K", "8") or "8").strip().strip('"').strip("'") or "8"
    )
    # Cross-encoder rerank для справочника (отдельно от RAG_USE_RERANKER по делу).
    LEGAL_CORPUS_USE_RERANKER: bool = os.getenv(
        "LEGAL_CORPUS_USE_RERANKER", "true"
    ).strip().lower() == "true"
    # После article fast path с полным покрытием плана — не гонять cross-encoder rerank по пулу.
    LEGAL_CORPUS_SKIP_RERANK_ON_FAST_PATH: bool = os.getenv(
        "LEGAL_CORPUS_SKIP_RERANK_ON_FAST_PATH", "true"
    ).strip().lower() == "true"
    # Усечение текста чанка для пары query–passage в reranker (heavy tier).
    LEGAL_CORPUS_RERANK_MAX_CHARS: int = int(
        (os.getenv("LEGAL_CORPUS_RERANK_MAX_CHARS", "2400") or "2400").strip().strip('"').strip("'")
        or "2400"
    )
    # light — как CASE_ASSISTANT (ms-marco-MiniLM); heavy — BGE / RERANKER_MODEL_NAME
    LEGAL_CORPUS_RERANK_TIER: str = (
        (os.getenv("LEGAL_CORPUS_RERANK_TIER", "light") or "light").strip().lower()
    )
    # Параллельный hybrid по search_queries (несколько embedding-запросов одновременно)
    LEGAL_CORPUS_HYBRID_PARALLEL: bool = os.getenv(
        "LEGAL_CORPUS_HYBRID_PARALLEL", "true"
    ).strip().lower() == "true"
    LEGAL_CORPUS_HYBRID_MAX_WORKERS: int = int(
        (os.getenv("LEGAL_CORPUS_HYBRID_MAX_WORKERS", "5") or "5").strip().strip('"').strip("'")
        or "5"
    )
    # Dense/sparse blend для norm-hybrid справочника (GLOBAL_LEGAL_CORPUS).
    LEGAL_CORPUS_HYBRID_ALPHA: float = float(
        (os.getenv("LEGAL_CORPUS_HYBRID_ALPHA", "0.7") or "0.7").strip().strip('"').strip("'") or "0.7"
    )
    # Внутренний чат (garant): размер выборки и лимит символов контекста справочника.
    LEGAL_CORPUS_CONTEXT_K: int = int(
        (os.getenv("LEGAL_CORPUS_CONTEXT_K", "8") or "8").strip().strip('"').strip("'") or "8"
    )
    LEGAL_CORPUS_MAX_CONTEXT_CHARS: int = int(
        (os.getenv("LEGAL_CORPUS_MAX_CONTEXT_CHARS", "14000") or "14000").strip().strip('"').strip("'")
        or "14000"
    )
    # Макс. символов тела одного фрагмента в контексте справочника (чтобы один чанк не съедал весь бюджет).
    LEGAL_CORPUS_MAX_FRAGMENT_CHARS: int = int(
        (os.getenv("LEGAL_CORPUS_MAX_FRAGMENT_CHARS", "2800") or "2800").strip().strip('"').strip("'")
        or "2800"
    )
    # Глобальный ассистент: минимум слотов для legal_corpus после merge с matter.
    LEGAL_CORPUS_GLOBAL_MERGE_MIN_SLOTS: int = int(
        (os.getenv("LEGAL_CORPUS_GLOBAL_MERGE_MIN_SLOTS", "3") or "3").strip().strip('"').strip("'")
        or "3"
    )
    # LLM pre-retrieval: переводит бытовой вопрос в юридические поисковые запросы перед первым поиском.
    GLOBAL_LEGAL_QUERY_INTERPRETER_ENABLED: bool = os.getenv(
        "GLOBAL_LEGAL_QUERY_INTERPRETER_ENABLED", "true"
    ).strip().lower() == "true"
    # Глобальный ассистент: второй проход retrieval по legal_corpus (итеративный добор, см. LangGraph agentic RAG).
    GLOBAL_LEGAL_ITERATIVE_RETRIEVAL_ENABLED: bool = os.getenv(
        "GLOBAL_LEGAL_ITERATIVE_RETRIEVAL_ENABLED", "true"
    ).strip().lower() == "true"
    # Максимум дополнительных поисковых строк за один запрос (после первого merge).
    GLOBAL_LEGAL_ITERATIVE_MAX_QUERIES: int = int(
        (os.getenv("GLOBAL_LEGAL_ITERATIVE_MAX_QUERIES", "3") or "3").strip().strip('"').strip("'") or "3"
    )
    # k на каждый follow-up запрос (меньше основного прохода, чтобы уложиться в бюджет).
    GLOBAL_LEGAL_ITERATIVE_K_PER_QUERY: int = int(
        (os.getenv("GLOBAL_LEGAL_ITERATIVE_K_PER_QUERY", "6") or "6").strip().strip('"').strip("'") or "6"
    )
    # Legal corpus agent: макс. hybrid-запросов за один turn (без LLM query interpreter на первом проходе).
    LEGAL_CORPUS_MAX_HYBRID_QUERIES: int = int(
        (os.getenv("LEGAL_CORPUS_MAX_HYBRID_QUERIES", "3") or "3").strip().strip('"').strip("'") or "3"
    )
    # Wall-clock бюджет на retrieval справочника в одном turn (мс); после — partial context.
    LEGAL_CORPUS_RETRIEVAL_WALL_MS: int = int(
        (os.getenv("LEGAL_CORPUS_RETRIEVAL_WALL_MS", "30000") or "30000").strip().strip('"').strip("'")
        or "30000"
    )
    # LLM query interpreter только на follow-up, не до первого hybrid (экономия latency).
    LEGAL_CORPUS_QUERY_INTERPRETER_ON_FIRST_PASS: bool = os.getenv(
        "LEGAL_CORPUS_QUERY_INTERPRETER_ON_FIRST_PASS", "false"
    ).strip().lower() == "true"
    # Таймаут выполнения global-assistant LangGraph (секунды).
    GLOBAL_ASSISTANT_GRAPH_TIMEOUT_SEC: int = int(
        (os.getenv("GLOBAL_ASSISTANT_GRAPH_TIMEOUT_SEC", "360") or "360").strip().strip('"').strip("'")
        or "360"
    )
    # Опционально: подсказка для embedding_text по instrument_id (без LLM, статический текст).
    LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED: bool = os.getenv(
        "LEGAL_CORPUS_EMBED_SYNONYM_HINTS_ENABLED", "true"
    ).strip().lower() == "true"
    # Справочник: article/clause chunking вместо macro/micro (фаза A).
    LEGAL_CORPUS_NORM_CHUNKING_ENABLED: bool = os.getenv(
        "LEGAL_CORPUS_NORM_CHUNKING_ENABLED", "true"
    ).strip().lower() == "true"
    LEGAL_CORPUS_NORM_MAX_ARTICLE_CHARS: int = int(
        os.getenv("LEGAL_CORPUS_NORM_MAX_ARTICLE_CHARS", "12000") or "12000"
    )
    # PDF законов: PyMuPDF text extract + очистка (consultant_pdf_preprocess).
    LEGAL_CORPUS_PDF_PREPROCESS_ENABLED: bool = os.getenv(
        "LEGAL_CORPUS_PDF_PREPROCESS_ENABLED", "true"
    ).strip().lower() == "true"
    # True = только text extract (без Docling AST) для PDF в справочнике.
    LEGAL_CORPUS_PDF_TEXT_FIRST: bool = os.getenv(
        "LEGAL_CORPUS_PDF_TEXT_FIRST", "false"
    ).strip().lower() == "true"
    # Graph expand при retrieval (фаза B).
    LEGAL_NORM_GRAPH_EXPAND_ENABLED: bool = os.getenv(
        "LEGAL_NORM_GRAPH_EXPAND_ENABLED", "true"
    ).strip().lower() == "true"
    LEGAL_NORM_GRAPH_EXPAND_LIMIT: int = int(
        os.getenv("LEGAL_NORM_GRAPH_EXPAND_LIMIT", "8") or "8"
    )
    # Многошаговый обход графа (BFS): 1 = только соседи, 2–3 = паутина.
    LEGAL_NORM_GRAPH_MAX_HOPS: int = int(os.getenv("LEGAL_NORM_GRAPH_MAX_HOPS", "2") or "2")
    LEGAL_NORM_GRAPH_TOTAL_EXPAND_LIMIT: int = int(
        os.getenv("LEGAL_NORM_GRAPH_TOTAL_EXPAND_LIMIT", "24") or "24"
    )
    # Graph-first: кластер норм по статьям из LLM-плана до hybrid retrieval.
    LEGAL_NORM_GRAPH_CLUSTER_ENABLED: bool = os.getenv(
        "LEGAL_NORM_GRAPH_CLUSTER_ENABLED", "true"
    ).strip().lower() == "true"
    LEGAL_NORM_GRAPH_CLUSTER_LIMIT: int = int(
        os.getenv("LEGAL_NORM_GRAPH_CLUSTER_LIMIT", "20") or "20"
    )
    # После загрузки главы: reconcile cross-ref + NEXT по всему instrument_id.
    LEGAL_NORM_GRAPH_RECONCILE_ON_UPLOAD: bool = os.getenv(
        "LEGAL_NORM_GRAPH_RECONCILE_ON_UPLOAD", "true"
    ).strip().lower() == "true"
    # Строгая валидация индекса (сбой загрузки при пустом графе/нормах).
    LEGAL_CORPUS_INDEX_GRAPH_VALIDATION_STRICT: bool = os.getenv(
        "LEGAL_CORPUS_INDEX_GRAPH_VALIDATION_STRICT", "false"
    ).strip().lower() == "true"
    # LLM extractor для неразрешённых отсылок при индексации (фаза E).
    LEGAL_NORM_LLM_EXTRACTOR_ENABLED: bool = os.getenv(
        "LEGAL_NORM_LLM_EXTRACTOR_ENABLED", "false"
    ).strip().lower() == "true"
    LEGAL_NORM_LLM_EXTRACTOR_MODEL: str = os.getenv("LEGAL_NORM_LLM_EXTRACTOR_MODEL", "").strip()

    # Dual legal-aware chunker (LegalChunkerV2, contract v2.1).
    # При True все новые загрузки в дело и Справочник идут через Docling AST → macro/micro.
    # На ошибке Docling/AST автоматически fallback на strict docling-direct-v1.
    LEGAL_CHUNKING_DUAL_ENABLED: bool = (
        os.getenv("LEGAL_CHUNKING_DUAL_ENABLED", "true").strip().lower() == "true"
    )
    # Один AST-сегмент длиннее этого (символы) — дробим до macro-слоя (Docling TableItem / длинный TextItem).
    LEGAL_SEGMENT_MAX_CHARS: int = int(os.getenv("LEGAL_SEGMENT_MAX_CHARS", "2200") or "2200")
    # Таблица в markdown длиннее — шардирование по строкам с повтором header.
    LEGAL_TABLE_SHARD_MIN_CHARS: int = int(os.getenv("LEGAL_TABLE_SHARD_MIN_CHARS", "1500") or "1500")
    LEGAL_TABLE_SHARD_ROWS_PER_GROUP: int = int(os.getenv("LEGAL_TABLE_SHARD_ROWS_PER_GROUP", "8") or "8")
    # Hidden context: префикс breadcrumbs только в embedding_text (см. metadata), page_content без префикса.
    LEGAL_CHUNK_EMBED_PREFIX_ENABLED: bool = (
        os.getenv("LEGAL_CHUNK_EMBED_PREFIX_ENABLED", "true").strip().lower() == "true"
    )
    # WARNING если один файл дал больше стольки чанков (парсер/шум).
    LEGAL_CHUNK_COUNT_WARN_THRESHOLD: int = int(
        os.getenv("LEGAL_CHUNK_COUNT_WARN_THRESHOLD", "2000") or "2000"
    )
    # Профиль чанкинга по умолчанию, если doc_type не классифицирован.
    # Допустимые значения: "regulations" | "court_docs" | "contracts".
    LEGAL_CHUNKING_DEFAULT_PROFILE: str = (
        os.getenv("LEGAL_CHUNKING_DEFAULT_PROFILE", "contracts").strip().lower()
    )

    # Structured table indexing (bank statements, registers) — contract structured-table-v1.
    STRUCTURED_TABLE_INDEXING_ENABLED: bool = (
        os.getenv("STRUCTURED_TABLE_INDEXING_ENABLED", "true").strip().lower() == "true"
    )
    STRUCTURED_TABLE_MIN_CHAR_RATIO: float = float(
        os.getenv("STRUCTURED_TABLE_MIN_CHAR_RATIO", "0.45") or "0.45"
    )
    STRUCTURED_TABLE_MIN_ROWS: int = int(os.getenv("STRUCTURED_TABLE_MIN_ROWS", "8") or "8")
    STRUCTURED_TABLE_MIN_TABLE_SEGMENTS: int = int(
        os.getenv("STRUCTURED_TABLE_MIN_TABLE_SEGMENTS", "1") or "1"
    )

    # Temporary: case chat graph + HTTP prep exactly like commit 0018729 (no SQL/hybrid router).
  # Set true to A/B test latency vs structured-data stack.
    CASE_ASSISTANT_LEGACY_PIPELINE_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_LEGACY_PIPELINE_ENABLED", "false").strip().lower()
        in ("1", "true", "yes")
    )
    # Per-turn planner: scope shortcuts, draft generation, rerank policy, deadlines.
    CASE_ASSISTANT_QUERY_PLANNER_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_QUERY_PLANNER_ENABLED", "true").strip().lower()
        in ("1", "true", "yes")
    )
    CASE_ASSISTANT_DRAFT_GENERATION_MODEL: str = os.getenv(
        "CASE_ASSISTANT_DRAFT_GENERATION_MODEL",
        "",
    ).strip()
    CASE_ASSISTANT_SCOPE_ROUTER_DEADLINE_MS: int = int(
        os.getenv("CASE_ASSISTANT_SCOPE_ROUTER_DEADLINE_MS", "2500") or "2500"
    )
    CASE_ASSISTANT_RERANK_DEADLINE_MS: int = int(
        os.getenv("CASE_ASSISTANT_RERANK_DEADLINE_MS", "1200") or "1200"
    )
    CASE_ASSISTANT_GENERATION_TTFT_BUDGET_MS: int = int(
        os.getenv("CASE_ASSISTANT_GENERATION_TTFT_BUDGET_MS", "3000") or "3000"
    )

    # SQL store for structured-table rows (bank statements) — chat tools list/aggregate.
    # Revert quickly: CASE_FILE_TRANSACTIONS_ENABLED=false
    CASE_FILE_TRANSACTIONS_ENABLED: bool = (
        os.getenv("CASE_FILE_TRANSACTIONS_ENABLED", "true").strip().lower() == "true"
    )
    # Tool-calling agent for statement queries (replaces regex fast-path).
    CASE_TRANSACTION_AGENT_ENABLED: bool = (
        os.getenv("CASE_TRANSACTION_AGENT_ENABLED", "true").strip().lower() == "true"
    )
    # LLM router: SQL transaction agent vs document RAG (same model as main assistant).
    STRUCTURED_DATA_LLM_ROUTER_ENABLED: bool = (
        os.getenv("STRUCTURED_DATA_LLM_ROUTER_ENABLED", "true").strip().lower() == "true"
    )
    STRUCTURED_DATA_LLM_ROUTER_MIN_CONF: float = float(
        os.getenv("STRUCTURED_DATA_LLM_ROUTER_MIN_CONF", "0.65") or "0.65"
    )
    STRUCTURED_DATA_LLM_ROUTER_MAX_TOKENS: int = int(
        os.getenv("STRUCTURED_DATA_LLM_ROUTER_MAX_TOKENS", "512") or "512"
    )
    STRUCTURED_DATA_LLM_ROUTER_MAX_FILES: int = int(
        os.getenv("STRUCTURED_DATA_LLM_ROUTER_MAX_FILES", "40") or "40"
    )
    # Run router in HTTP prep (before session embeddings); graph reuses result.
    STRUCTURED_DATA_HTTP_PREP_ROUTER_ENABLED: bool = (
        os.getenv("STRUCTURED_DATA_HTTP_PREP_ROUTER_ENABLED", "true").strip().lower() == "true"
    )
    # Single LLM: turn context + SQL/RAG routing (replaces judge + structured router).
    CASE_TURN_PREP_UNIFIED_PLANNER_ENABLED: bool = (
        os.getenv("CASE_TURN_PREP_UNIFIED_PLANNER_ENABLED", "false").strip().lower() == "true"
    )
    CASE_TURN_PREP_UNIFIED_PLANNER_MODEL: str = clean_env_str(
        os.getenv("CASE_TURN_PREP_UNIFIED_PLANNER_MODEL"), ""
    )
    CASE_TURN_PREP_UNIFIED_PLANNER_MAX_TOKENS: int = int(
        os.getenv("CASE_TURN_PREP_UNIFIED_PLANNER_MAX_TOKENS", "640") or "640"
    )
    # Statement SQL: LLM planner → deterministic executor (count/sum/list/find/top/group).
    STATEMENT_SQL_PLANNER_ENABLED: bool = (
        os.getenv("STATEMENT_SQL_PLANNER_ENABLED", "true").strip().lower() == "true"
    )
    STATEMENT_SQL_PLANNER_MIN_CONF: float = float(
        os.getenv("STATEMENT_SQL_PLANNER_MIN_CONF", "0.65") or "0.65"
    )
    STATEMENT_SQL_PLANNER_MAX_TOKENS: int = int(
        os.getenv("STATEMENT_SQL_PLANNER_MAX_TOKENS", "512") or "512"
    )
    # Tool-calling agent over one statement table (primary path; classic planner is fallback).
    STATEMENT_TABLE_AGENT_ENABLED: bool = (
        os.getenv("STATEMENT_TABLE_AGENT_ENABLED", "true").strip().lower() == "true"
    )
    STATEMENT_TABLE_AGENT_MAX_TOOL_CALLS: int = int(
        os.getenv("STATEMENT_TABLE_AGENT_MAX_TOOL_CALLS", "8") or "8"
    )
    STATEMENT_TABLE_AGENT_MAX_TOKENS: int = int(
        os.getenv("STATEMENT_TABLE_AGENT_MAX_TOKENS", "2048") or "2048"
    )
    # LLM формулирует ответ по структурированным фактам SQL (fallback — краткий детерминированный текст).
    STATEMENT_SQL_SYNTHESIS_ENABLED: bool = (
        os.getenv("STATEMENT_SQL_SYNTHESIS_ENABLED", "true").strip().lower() == "true"
    )
    STATEMENT_SQL_SYNTHESIS_MODEL: str = clean_env_str(
        os.getenv("STATEMENT_SQL_SYNTHESIS_MODEL"), ""
    )
    STATEMENT_SQL_SYNTHESIS_MAX_TOKENS: int = int(
        os.getenv("STATEMENT_SQL_SYNTHESIS_MAX_TOKENS", "1024") or "1024"
    )
    STATEMENT_SQL_SYNTHESIS_MAX_ROWS: int = int(
        os.getenv("STATEMENT_SQL_SYNTHESIS_MAX_ROWS", "40") or "40"
    )
    OPERATIONS_CHAT_SCOPE_MAX_ROWS: int = int(
        os.getenv("OPERATIONS_CHAT_SCOPE_MAX_ROWS", "20000") or "20000"
    )
    OPERATIONS_CHAT_HISTORY_MAX_TURNS: int = int(
        os.getenv("OPERATIONS_CHAT_HISTORY_MAX_TURNS", "6") or "6"
    )
    # Shared file-scoped agent (SQL + RAG) for chat and tabular statement cells.
    FILE_SCOPED_AGENT_ENABLED: bool = (
        os.getenv("FILE_SCOPED_AGENT_ENABLED", "true").strip().lower() == "true"
    )
    TABULAR_STATEMENT_AGENT_ENABLED: bool = (
        os.getenv("TABULAR_STATEMENT_AGENT_ENABLED", "true").strip().lower() == "true"
    )
    # Tabular cells on SQL-flagged files: router (rag/sql/hybrid) like case chat.
    TABULAR_CELL_DATA_ROUTER_ENABLED: bool = (
        os.getenv("TABULAR_CELL_DATA_ROUTER_ENABLED", "true").strip().lower() == "true"
    )

    # Docling pipeline limits (используются document_converter_service и legal_chunker).
    # 2000 страниц закрывает крупные кодексы (ГК РФ ~1.2k стр., НК РФ ~1.5k стр.).
    DOCLING_MAX_PAGES_PER_DOC: int = int(
        os.getenv("DOCLING_MAX_PAGES_PER_DOC", "2000") or "2000"
    )
    DOCLING_MAX_FILE_SIZE_BYTES: int = int(
        os.getenv("DOCLING_MAX_FILE_SIZE_BYTES", str(60 * 1024 * 1024)) or str(60 * 1024 * 1024)
    )
    # Large-PDF ingest: convert page windows instead of one-shot DoclingDocument.
    # Defaults tuned for weak/medium Yandex VMs (Docling parallel=1, limited RAM).
    DOCLING_PDF_BATCH_ENABLED: bool = (
        os.getenv("DOCLING_PDF_BATCH_ENABLED", "true").strip().lower() == "true"
    )
    DOCLING_PDF_BATCH_PAGES: int = int(os.getenv("DOCLING_PDF_BATCH_PAGES", "30") or "30")
    # Only batch when page count reaches this threshold (small PDFs stay one-shot).
    DOCLING_PDF_BATCH_MIN_PAGES: int = int(
        os.getenv("DOCLING_PDF_BATCH_MIN_PAGES", "40") or "40"
    )
    DOCLING_PDF_TABLE_MODE: str = os.getenv("DOCLING_PDF_TABLE_MODE", "accurate").strip().lower()
    DOCLING_PDF_TABLE_STRUCTURE: bool = (
        os.getenv("DOCLING_PDF_TABLE_STRUCTURE", "true").strip().lower() == "true"
    )
    DOCLING_PDF_TABLE_CELL_MATCHING: bool = (
        os.getenv("DOCLING_PDF_TABLE_CELL_MATCHING", "true").strip().lower() == "true"
    )
    DOCLING_ENABLE_REMOTE_SERVICES: bool = (
        os.getenv("DOCLING_ENABLE_REMOTE_SERVICES", "false").strip().lower() == "true"
    )
    # Движок OCR внутри Docling PDF pipeline: auto | easyocr | tesseract_cli
    DOCLING_PDF_OCR_ENGINE: str = clean_env_str(os.getenv("DOCLING_PDF_OCR_ENGINE"), "auto").lower()
    DOCLING_OCR_FORCE_FULL_PAGE: bool = (
        clean_env_str(os.getenv("DOCLING_OCR_FORCE_FULL_PAGE"), "false").lower() == "true"
    )
    DOCLING_OCR_BITMAP_AREA_THRESHOLD: float = float(
        os.getenv("DOCLING_OCR_BITMAP_AREA_THRESHOLD", "0.05") or "0.05"
    )
    DOCLING_ARTIFACTS_PATH: str = os.getenv("DOCLING_ARTIFACTS_PATH", "").strip()
    # EasyOCR (ISO 639-1): ru,en,…
    DOCLING_OCR_EASYOCR_LANGS: str = clean_env_str(os.getenv("DOCLING_OCR_EASYOCR_LANGS"), "ru,en")
    # Tesseract CLI в Docling: трёхбуквенные коды через запятую или rus+eng
    DOCLING_OCR_TESSERACT_LANGS: str = os.getenv("DOCLING_OCR_TESSERACT_LANGS", "rus,eng").strip()
    # Для do_ocr=auto: переопределить lang у выбранного движка (формат зависит от движка; часто пусто = дефолты Docling)
    DOCLING_OCR_LANGUAGES: list[str] = [
        x.strip()
        for x in os.getenv("DOCLING_OCR_LANGUAGES", "").split(",")
        if x.strip()
    ]
    # Прогрев кэшированного DocumentConverter при старте API (native PDF ingest path).
    DOCLING_WARMUP_ON_STARTUP: bool = (
        os.getenv("DOCLING_WARMUP_ON_STARTUP", "true").strip().lower() == "true"
    )

    # LLM context limits
    MAX_CONTEXT_CHARS: int = 60_000  # Приближённо к лимиту ~32k токенов
    
    # RAG Settings
    RAG_USE_RERANKER: bool = os.getenv("RAG_USE_RERANKER", "false").lower() == "true"  # Use cross-encoder reranker for relevance scoring
    RERANKER_MODEL_NAME: str = os.getenv(
        "RERANKER_MODEL_NAME",
        "BAAI/bge-reranker-v2-m3",
    ).strip()
    RAG_MIN_RELEVANCE_SCORE: float = float(os.getenv("RAG_MIN_RELEVANCE_SCORE", "0.5"))  # Minimum relevance score threshold
    RAG_LLM_EVALUATION_ENABLED: bool = os.getenv("RAG_LLM_EVALUATION_ENABLED", "true").lower() == "true"  # Enable LLM-based relevance evaluation
    RAG_REQUIRE_SOURCES: bool = os.getenv("RAG_REQUIRE_SOURCES", "true").lower() == "true"  # Require source citations in answers
    RAG_ALLOW_UNCERTAINTY: bool = os.getenv("RAG_ALLOW_UNCERTAINTY", "true").lower() == "true"  # Allow model to express uncertainty when information is insufficient
    RAG_LANGGRAPH_STRUCTURED_CITATIONS_ENABLED: bool = (
        os.getenv("RAG_LANGGRAPH_STRUCTURED_CITATIONS_ENABLED", "true").lower() == "true"
    )
    # Stream structured-citation answers (text_delta + progressive citations) instead of sync invoke.
    RAG_STRUCTURED_CITATIONS_STREAM_ENABLED: bool = (
        os.getenv("RAG_STRUCTURED_CITATIONS_STREAM_ENABLED", "true").lower() == "true"
    )
    # Editor document chat: stream tokens via Yandex OpenAI-compat (stream=true).
    EDITOR_CHAT_STREAM_ENABLED: bool = (
        os.getenv("EDITOR_CHAT_STREAM_ENABLED", "true").lower() == "true"
    )
    # Max document HTML chars from frontend (full doc or selection-only slice).
    EDITOR_DOCUMENT_CONTEXT_MAX_CHARS: int = int(
        os.getenv("EDITOR_DOCUMENT_CONTEXT_MAX_CHARS", "80000") or "80000"
    )
    # Подробные логи [EditorLatency] + SSE latency_debug в стриме редактора.
    EDITOR_LATENCY_VERBOSE: bool = (
        os.getenv("EDITOR_LATENCY_VERBOSE", "true").lower() == "true"
    )
    # Редактор: START → mode_router без manage_memory (история в editor_transcript, без LLM-summary).
    EDITOR_FAST_MEMORY_PATH: bool = (
        os.getenv("EDITOR_FAST_MEMORY_PATH", "true").lower() == "true"
    )
    # Скрепка в редакторе: до N файлов целиком (structured_text), без RAG
    EDITOR_ATTACH_FULL_TEXT_ENABLED: bool = (
        os.getenv("EDITOR_ATTACH_FULL_TEXT_ENABLED", "true").lower() == "true"
    )
    EDITOR_ATTACH_MAX_FILES: int = int(os.getenv("EDITOR_ATTACH_MAX_FILES", "3") or "3")
    EDITOR_ATTACH_MAX_CHARS_PER_FILE: int = int(
        os.getenv("EDITOR_ATTACH_MAX_CHARS_PER_FILE", "80000") or "80000"
    )
    EDITOR_ATTACH_MAX_CHARS_TOTAL: int = int(
        os.getenv("EDITOR_ATTACH_MAX_CHARS_TOTAL", "120000") or "120000"
    )
    # Edit mode: full HTML in generate_edits prompt when document is smaller than this.
    EDITOR_GENERATE_EDITS_FULL_HTML_THRESHOLD: int = int(
        os.getenv("EDITOR_GENERATE_EDITS_FULL_HTML_THRESHOLD", "12000") or "12000"
    )
    # Large documents: max blocks with full HTML included alongside outline.
    EDITOR_GENERATE_EDITS_RELEVANT_BLOCK_LIMIT: int = int(
        os.getenv("EDITOR_GENERATE_EDITS_RELEVANT_BLOCK_LIMIT", "8") or "8"
    )
    EDITOR_GENERATE_EDITS_BLOCK_SNIPPETS_MAX_CHARS: int = int(
        os.getenv("EDITOR_GENERATE_EDITS_BLOCK_SNIPPETS_MAX_CHARS", "20000") or "20000"
    )
    EDITOR_GENERATE_EDITS_FALLBACK_HTML_CHARS: int = int(
        os.getenv("EDITOR_GENERATE_EDITS_FALLBACK_HTML_CHARS", "16000") or "16000"
    )
    # Mass edit approval threshold (client applies patches; server only messages).
    EDITOR_MASS_EDIT_APPROVAL_THRESHOLD: int = int(
        os.getenv("EDITOR_MASS_EDIT_APPROVAL_THRESHOLD", "10") or "10"
    )
    FILE_STRUCTURED_TEXT_MAX_STORE_CHARS: int = int(
        os.getenv("FILE_STRUCTURED_TEXT_MAX_STORE_CHARS", "2000000") or "2000000"
    )
    # Прогрев ChatGraph при старте API (убирает ~3s compile на первом запросе).
    CHAT_GRAPH_WARMUP_ON_STARTUP: bool = (
        os.getenv("CHAT_GRAPH_WARMUP_ON_STARTUP", "true").lower() == "true"
    )

    # Fast retrieval tuning (case assistant / LangGraph RAG node)
    # Avoid multi-query LLM expansion + multi-pass k_schedule for depth_tier=fast by default.
    RAG_FAST_RETRIEVAL_STRATEGY: str = os.getenv(
        "RAG_FAST_RETRIEVAL_STRATEGY", "similarity"
    ).strip().lower()
    # Per-retrieve_context call wall timeout (seconds). 0 disables.
    RAG_FAST_RETRIEVAL_CALL_TIMEOUT_SEC: float = float(
        os.getenv("RAG_FAST_RETRIEVAL_CALL_TIMEOUT_SEC", "25") or "25"
    )
    # If fast single-pass returns fewer than N docs, allow one multi_query fallback (extra LLM call).
    RAG_FAST_MULTIQUERY_FALLBACK: bool = os.getenv(
        "RAG_FAST_MULTIQUERY_FALLBACK", "true"
    ).lower() == "true"
    RAG_FAST_FALLBACK_MIN_DOCS: int = int(os.getenv("RAG_FAST_FALLBACK_MIN_DOCS", "2") or "2")

    # Case assistant context pipeline (scope router → hybrid recall → rerank → LLM)
    CASE_ASSISTANT_CONTEXT_PIPELINE_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_CONTEXT_PIPELINE_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_LLM_ROUTER_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_LLM_ROUTER_ENABLED", "true").strip().lower() == "true"
    )
    # FAST path: allow a cheap lite LLM call to pick file_ids from the catalog
    # when deterministic №-ref / summary scope miss. Keeps prep LLMs skipped.
    CASE_ASSISTANT_FAST_LLM_FILE_SCOPE_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_FAST_LLM_FILE_SCOPE_ENABLED", "true").strip().lower()
        == "true"
    )
    CASE_ASSISTANT_ROUTER_MODEL: str = os.getenv(
        "CASE_ASSISTANT_ROUTER_MODEL",
        os.getenv("YANDEX_GPT_MODEL", "yandexgpt-lite/latest"),
    ).strip()
    CASE_ASSISTANT_ROUTER_MIN_CONFIDENCE: float = float(
        os.getenv("CASE_ASSISTANT_ROUTER_MIN_CONFIDENCE", "0.55") or "0.55"
    )
    CASE_ASSISTANT_ROUTER_MAX_CATALOG_FILES: int = int(
        os.getenv("CASE_ASSISTANT_ROUTER_MAX_CATALOG_FILES", "80") or "80"
    )
    # Дела с числом файлов <= порога: без выбора документов — chunk search по всему делу.
    CASE_ASSISTANT_ROUTER_SMALL_CASE_MAX_FILES: int = int(
        os.getenv("CASE_ASSISTANT_ROUTER_SMALL_CASE_MAX_FILES", "5") or "5"
    )
    # Deprecated: keyword/heuristic-first routing removed; kept for env compat only.
    CASE_ASSISTANT_ROUTER_HEURISTIC_FIRST: bool = (
        os.getenv("CASE_ASSISTANT_ROUTER_HEURISTIC_FIRST", "false").strip().lower() == "true"
    )
    CASE_ASSISTANT_ROUTER_HEURISTIC_MIN_CONFIDENCE: float = float(
        os.getenv("CASE_ASSISTANT_ROUTER_HEURISTIC_MIN_CONFIDENCE", "0.72") or "0.72"
    )
    CASE_ASSISTANT_CATALOG_CACHE_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_CATALOG_CACHE_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_CATALOG_CACHE_TTL_SEC: int = int(
        os.getenv("CASE_ASSISTANT_CATALOG_CACHE_TTL_SEC", "600") or "600"
    )
    CASE_ASSISTANT_DOC_COUNT_CACHE_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_DOC_COUNT_CACHE_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_DOC_COUNT_CACHE_TTL_SEC: int = int(
        os.getenv("CASE_ASSISTANT_DOC_COUNT_CACHE_TTL_SEC", "300") or "300"
    )
    # Instant/fact answers: keep prompt small for TTFT (full tiers stay large).
    CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS: int = int(
        os.getenv("CASE_ASSISTANT_INSTANT_MAX_CONTEXT_CHARS", "3500") or "3500"
    )
    CASE_ASSISTANT_STANDARD_MAX_CONTEXT_CHARS: int = int(
        os.getenv("CASE_ASSISTANT_STANDARD_MAX_CONTEXT_CHARS", "48000") or "48000"
    )
    CASE_ASSISTANT_DEEP_MAX_CONTEXT_CHARS: int = int(
        os.getenv("CASE_ASSISTANT_DEEP_MAX_CONTEXT_CHARS", "64000") or "64000"
    )
    CASE_ASSISTANT_MAX_CONTEXT_CHARS_CEILING: int = int(
        os.getenv("CASE_ASSISTANT_MAX_CONTEXT_CHARS_CEILING", "48000") or "48000"
    )
    CASE_ASSISTANT_INSTANT_MAX_TOKENS: int = int(
        os.getenv("CASE_ASSISTANT_INSTANT_MAX_TOKENS", "300") or "300"
    )
    # FAST latency path generation ceilings (same model; smaller prompt/output).
    CASE_ASSISTANT_FAST_GEN_MAX_CONTEXT_CHARS: int = int(
        os.getenv("CASE_ASSISTANT_FAST_GEN_MAX_CONTEXT_CHARS", "3500") or "3500"
    )
    CASE_ASSISTANT_FAST_GEN_MAX_TOKENS: int = int(
        os.getenv("CASE_ASSISTANT_FAST_GEN_MAX_TOKENS", "300") or "300"
    )
    CASE_ASSISTANT_STANDARD_MAX_TOKENS: int = int(
        os.getenv("CASE_ASSISTANT_STANDARD_MAX_TOKENS", "1500") or "1500"
    )
    CASE_ASSISTANT_DEEP_MAX_TOKENS: int = int(
        os.getenv("CASE_ASSISTANT_DEEP_MAX_TOKENS", "4500") or "4500"
    )
    CASE_ASSISTANT_INSTANT_TEMPERATURE: float = float(
        os.getenv("CASE_ASSISTANT_INSTANT_TEMPERATURE", "0.1") or "0.1"
    )
    CASE_ASSISTANT_STANDARD_TEMPERATURE: float = float(
        os.getenv("CASE_ASSISTANT_STANDARD_TEMPERATURE", "0.2") or "0.2"
    )
    CASE_ASSISTANT_DEEP_TEMPERATURE: float = float(
        os.getenv("CASE_ASSISTANT_DEEP_TEMPERATURE", "0.3") or "0.3"
    )
    # File-level summary index (hierarchical RAG step 1): hybrid vector+FTS → dynamic K
    CASE_ASSISTANT_FILE_SUMMARY_INDEX_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_INDEX_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_FILE_SUMMARY_MIN_SCORE: float = float(
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_MIN_SCORE", "0.6") or "0.6"
    )
    CASE_ASSISTANT_FILE_SUMMARY_SCORE_GAP: float = float(
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_SCORE_GAP", "0.15") or "0.15"
    )
    CASE_ASSISTANT_FILE_SUMMARY_RECALL_K: int = int(
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_RECALL_K", "30") or "30"
    )
    CASE_ASSISTANT_FILE_SUMMARY_MAX_FILES: int = int(
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_MAX_FILES", "20") or "20"
    )
    CASE_ASSISTANT_FILE_SUMMARY_RELAXED_MIN_SCORE: float = float(
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_RELAXED_MIN_SCORE", "0.35") or "0.35"
    )
    CASE_ASSISTANT_FILE_SUMMARY_NEAR_MISS_TOP_K: int = int(
        os.getenv("CASE_ASSISTANT_FILE_SUMMARY_NEAR_MISS_TOP_K", "3") or "3"
    )
    # LLM scope secretary: max file_ids (0 = use FILE_SUMMARY_MAX_FILES)
    CASE_ASSISTANT_ROUTER_LLM_MAX_FILES: int = int(
        os.getenv("CASE_ASSISTANT_ROUTER_LLM_MAX_FILES", "0") or "0"
    )
    # full_case from LLM only when confidence >= this threshold
    CASE_ASSISTANT_ROUTER_FULL_CASE_MIN_CONFIDENCE: float = float(
        os.getenv("CASE_ASSISTANT_ROUTER_FULL_CASE_MIN_CONFIDENCE", "0.72") or "0.72"
    )
    # In-dialog session memory (thread state + semantic search + LLM resolver; no phrase triggers)
    SESSION_CONTEXT_ENABLED: bool = (
        os.getenv("SESSION_CONTEXT_ENABLED", "true").strip().lower() == "true"
    )
    SESSION_CONTEXT_SEMANTIC_ENABLED: bool = (
        os.getenv("SESSION_CONTEXT_SEMANTIC_ENABLED", "true").strip().lower() == "true"
    )
    SESSION_CONTEXT_RESOLVER_ENABLED: bool = (
        os.getenv("SESSION_CONTEXT_RESOLVER_ENABLED", "true").strip().lower() == "true"
    )
    SESSION_CONTEXT_INTENT_AUTHORITY_ENABLED: bool = (
        os.getenv("SESSION_CONTEXT_INTENT_AUTHORITY_ENABLED", "true").strip().lower() == "true"
    )
    SESSION_CONTEXT_INTENT_AUTHORITY_MIN_CONF: float = float(
        os.getenv("SESSION_CONTEXT_INTENT_AUTHORITY_MIN_CONF", "0.72") or "0.72"
    )
    SESSION_CONTEXT_THREAD_STATE_LLM_ENABLED: bool = (
        os.getenv("SESSION_CONTEXT_THREAD_STATE_LLM_ENABLED", "true").strip().lower() == "true"
    )
    SESSION_CONTEXT_SEARCH_K: int = int(os.getenv("SESSION_CONTEXT_SEARCH_K", "8") or "8")
    SESSION_CONTEXT_MAX_RELEVANT_TURNS: int = int(
        os.getenv("SESSION_CONTEXT_MAX_RELEVANT_TURNS", "5") or "5"
    )
    # Turn Context Contract — Phase 2 LLM-lite query expansion for deictic follow-ups
    TURN_CONTEXT_LLM_QUERY_RESOLVE_ENABLED: bool = (
        os.getenv("TURN_CONTEXT_LLM_QUERY_RESOLVE_ENABLED", "true").strip().lower() == "true"
    )
    TURN_CONTEXT_LLM_QUERY_MODEL: str = os.getenv(
        "TURN_CONTEXT_LLM_QUERY_MODEL",
        os.getenv("CASE_ASSISTANT_ROUTER_MODEL", "yandexgpt-lite/latest"),
    )
    TURN_CONTEXT_LLM_QUERY_MAX_TOKENS: int = int(
        os.getenv("TURN_CONTEXT_LLM_QUERY_MAX_TOKENS", "256") or "256"
    )
    # Turn Context Contract — primary LLM judge (memory vs scoped vs full retrieval)
    TURN_CONTEXT_LLM_JUDGE_ENABLED: bool = (
        os.getenv("TURN_CONTEXT_LLM_JUDGE_ENABLED", "true").strip().lower() == "true"
    )
    TURN_CONTEXT_LLM_JUDGE_MODEL: str = os.getenv(
        "TURN_CONTEXT_LLM_JUDGE_MODEL",
        os.getenv("TURN_CONTEXT_LLM_QUERY_MODEL", os.getenv("CASE_ASSISTANT_ROUTER_MODEL", "")),
    )
    TURN_CONTEXT_LLM_JUDGE_MAX_TOKENS: int = int(
        os.getenv("TURN_CONTEXT_LLM_JUDGE_MAX_TOKENS", "384") or "384"
    )
    TURN_CONTEXT_LLM_JUDGE_MIN_CONF: float = float(
        os.getenv("TURN_CONTEXT_LLM_JUDGE_MIN_CONF", "0.68") or "0.68"
    )
    TURN_CONTEXT_LLM_JUDGE_MAX_TURNS: int = int(
        os.getenv("TURN_CONTEXT_LLM_JUDGE_MAX_TURNS", "10") or "10"
    )
    SESSION_REPLAY_SEARCH_SCORE_MIN: float = float(
        os.getenv("SESSION_REPLAY_SEARCH_SCORE_MIN", "0.45") or "0.45"
    )
    # Raw chat history in global assistant answer prompt (session context / replay unchanged)
    GLOBAL_ASSISTANT_HISTORY_PROMPT_MAX_TURNS: int = int(
        os.getenv("GLOBAL_ASSISTANT_HISTORY_PROMPT_MAX_TURNS", "16") or "16"
    )
    GLOBAL_ASSISTANT_HISTORY_PROMPT_MAX_CHARS: int = int(
        os.getenv("GLOBAL_ASSISTANT_HISTORY_PROMPT_MAX_CHARS", "6400") or "6400"
    )
    GLOBAL_ASSISTANT_HISTORY_SUMMARIZE_AFTER_TURNS: int = int(
        os.getenv("GLOBAL_ASSISTANT_HISTORY_SUMMARIZE_AFTER_TURNS", "20") or "20"
    )
    # LangGraph short-term memory: messages + checkpointer (Postgres transcript is canonical)
    GLOBAL_ASSISTANT_CHECKPOINT_MESSAGES_ENABLED: bool = (
        os.getenv("GLOBAL_ASSISTANT_CHECKPOINT_MESSAGES_ENABLED", "true").strip().lower()
        == "true"
    )
    # Legacy transcript replay short-circuit (off when checkpoint messages are enabled)
    GLOBAL_ASSISTANT_TRANSCRIPT_REPLAY_ENABLED: bool = (
        os.getenv("GLOBAL_ASSISTANT_TRANSCRIPT_REPLAY_ENABLED", "false").strip().lower()
        == "true"
    )
    # Case-assistant LangGraph message memory (editor fast-path keeps tighter defaults)
    CASE_GRAPH_MEMORY_KEEP_LAST_N: int = int(
        os.getenv("CASE_GRAPH_MEMORY_KEEP_LAST_N", "12") or "12"
    )
    CASE_GRAPH_MEMORY_SUMMARIZE_THRESHOLD: int = int(
        os.getenv("CASE_GRAPH_MEMORY_SUMMARIZE_THRESHOLD", "24") or "24"
    )
    CASE_GRAPH_MEMORY_MAX_TOKENS: int = int(
        os.getenv("CASE_GRAPH_MEMORY_MAX_TOKENS", "8000") or "8000"
    )
    # Lite router only on summary-index miss (not on every question)
    CASE_ASSISTANT_LLM_ROUTER_FALLBACK_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_LLM_ROUTER_FALLBACK_ENABLED", "true").strip().lower() == "true"
    )
    # In-memory BM25 по делу: prewarm из PGVector в процессе API (не только worker).
    CASE_BM25_PREWARM_ENABLED: bool = (
        os.getenv("CASE_BM25_PREWARM_ENABLED", "true").strip().lower() == "true"
    )
    CASE_BM25_MAX_CHUNKS: int = int(os.getenv("CASE_BM25_MAX_CHUNKS", "2500") or "2500")
    # false: на запросе не блокировать построение BM25 (FTS + фоновый prewarm).
    CASE_BM25_SYNC_ON_HYBRID_SEARCH: bool = (
        os.getenv("CASE_BM25_SYNC_ON_HYBRID_SEARCH", "true").strip().lower() == "true"
    )
    # Слияние фоновых rebuild после серии store_in_vector_db (сек; 0 = без debounce).
    CASE_BM25_DEBOUNCE_SEC: float = float(os.getenv("CASE_BM25_DEBOUNCE_SEC", "1.5") or "1.5")
    CASE_ASSISTANT_RECALL_K: int = int(os.getenv("CASE_ASSISTANT_RECALL_K", "100") or "100")
    CASE_ASSISTANT_FINAL_K: int = int(os.getenv("CASE_ASSISTANT_FINAL_K", "15") or "15")
    # Tabular review: per-cell RAG (smaller than case chat — one file, one question)
    TABULAR_RECALL_K: int = int(os.getenv("TABULAR_RECALL_K", "30") or "30")
    TABULAR_FINAL_K: int = int(os.getenv("TABULAR_FINAL_K", "5") or "5")
    TABULAR_FINAL_K_SIMPLE: int = int(os.getenv("TABULAR_FINAL_K_SIMPLE", "3") or "3")
    TABULAR_CONTEXT_MAX_CHARS: int = int(
        os.getenv("TABULAR_CONTEXT_MAX_CHARS", "6000") or "6000"
    )
    # Tabular: cross-encoder rerank per cell (off by default — 17 parallel cells + rerank is very slow locally).
    TABULAR_RERANK_ENABLED: bool = (
        os.getenv("TABULAR_RERANK_ENABLED", "false").strip().lower() == "true"
    )
    TABULAR_MAX_PARALLEL_CELLS: int = int(
        os.getenv("TABULAR_MAX_PARALLEL_CELLS", "5") or "5"
    )
    TABULAR_EVIDENCE_REQUIRED: bool = (
        os.getenv("TABULAR_EVIDENCE_REQUIRED", "true").strip().lower() == "true"
    )
    TABULAR_CONFIDENCE_REVIEW_THRESHOLD: float = float(
        os.getenv("TABULAR_CONFIDENCE_REVIEW_THRESHOLD", "0.7") or "0.7"
    )
    TABULAR_CONFIDENCE_AUTO_COMPLETE_THRESHOLD: float = float(
        os.getenv("TABULAR_CONFIDENCE_AUTO_COMPLETE_THRESHOLD", "0.6") or "0.6"
    )
    CASE_ASSISTANT_RERANK_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_RERANK_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_RERANK_MAX_CHARS: int = int(
        os.getenv("CASE_ASSISTANT_RERANK_MAX_CHARS", "1200") or "1200"
    )
    # Core RAG: recall hybrid on micro chunks only; macro resolved after rerank
    CASE_ASSISTANT_MICRO_ONLY_RECALL_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_MICRO_ONLY_RECALL_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_MICRO_RECALL_K: int = int(
        os.getenv("CASE_ASSISTANT_MICRO_RECALL_K", "20") or "20"
    )
    CASE_ASSISTANT_PARENT_CONTEXT_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_PARENT_CONTEXT_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_RERANK_BATCH_SIZE: int = int(
        os.getenv("CASE_ASSISTANT_RERANK_BATCH_SIZE", "32") or "32"
    )
    CASE_ASSISTANT_RERANK_USE_COHERE: bool = (
        os.getenv("CASE_ASSISTANT_RERANK_USE_COHERE", "false").strip().lower() == "true"
    )
    CASE_ASSISTANT_RERANK_POOL_CAP: int = int(
        os.getenv("CASE_ASSISTANT_RERANK_POOL_CAP", "24") or "24"
    )
    CASE_ASSISTANT_SKIP_RERANK_WHEN_SUFFICIENT: bool = (
        os.getenv("CASE_ASSISTANT_SKIP_RERANK_WHEN_SUFFICIENT", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_SKIP_RERANK_MIN_RANK_GAP: float = float(
        os.getenv("CASE_ASSISTANT_SKIP_RERANK_MIN_RANK_GAP", "0.12") or "0.12"
    )
    CASE_ASSISTANT_OVERVIEW_SUMMARY_PATH_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_OVERVIEW_SUMMARY_PATH_ENABLED", "true").strip().lower()
        == "true"
    )
    CASE_ASSISTANT_RERANK_LIGHT_MODEL: str = os.getenv(
        "CASE_ASSISTANT_RERANK_LIGHT_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ).strip()
    CASE_ASSISTANT_RERANK_LIGHT_MAX_CHARS: int = int(
        os.getenv("CASE_ASSISTANT_RERANK_LIGHT_MAX_CHARS", "900") or "900"
    )
    CASE_ASSISTANT_RERANK_LIGHT_BATCH_SIZE: int = int(
        os.getenv("CASE_ASSISTANT_RERANK_LIGHT_BATCH_SIZE", "64") or "64"
    )
    # Recall + rerank in one executor (no separate graph-node cold gap)
    CASE_ASSISTANT_UNIFIED_RETRIEVAL: bool = (
        os.getenv("CASE_ASSISTANT_UNIFIED_RETRIEVAL", "true").strip().lower() == "true"
    )
    # Adaptive latency path: FAST document Q&A skips prep LLMs (default ON).
    # HEAVY only for UI toggles (draft/deep/127-FZ) and explicit heavy intents.
    CASE_ASSISTANT_LATENCY_PATH_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_LATENCY_PATH_ENABLED", "true").strip().lower() == "true"
    )
    # Weak retrieval → one deterministic broaden/deepen pass (no LLM rewrite on FAST).
    CASE_ASSISTANT_RETRIEVAL_ESCALATION_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_RETRIEVAL_ESCALATION_ENABLED", "true").strip().lower()
        == "true"
    )
    # When retrieval is scoped to concrete file(s), merge a within-file lexical
    # channel for compact documents (price / cadastral / clause recall).
    CASE_ASSISTANT_SCOPED_FILE_EXPAND_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_SCOPED_FILE_EXPAND_ENABLED", "true").strip().lower()
        == "true"
    )
    CASE_ASSISTANT_SCOPED_FILE_EXPAND_MAX_CHUNKS: int = int(
        os.getenv("CASE_ASSISTANT_SCOPED_FILE_EXPAND_MAX_CHUNKS", "48") or "48"
    )
    CASE_ASSISTANT_SCOPED_FILE_EXPAND_POOL: int = int(
        os.getenv("CASE_ASSISTANT_SCOPED_FILE_EXPAND_POOL", "32") or "32"
    )
    CASE_ASSISTANT_SCOPED_FILE_EXPAND_MAX_FILES: int = int(
        os.getenv("CASE_ASSISTANT_SCOPED_FILE_EXPAND_MAX_FILES", "3") or "3"
    )
    # Adaptive execution tiers (instant / standard / deep) — recall and rerank per tier
    CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_ADAPTIVE_TIER_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_INSTANT_RECALL_K: int = int(
        os.getenv("CASE_ASSISTANT_INSTANT_RECALL_K", "16") or "16"
    )
    CASE_ASSISTANT_STANDARD_RECALL_K: int = int(
        os.getenv("CASE_ASSISTANT_STANDARD_RECALL_K", "35") or "35"
    )
    CASE_ASSISTANT_TIER_LLM_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_TIER_LLM_ENABLED", "false").strip().lower() == "true"
    )
    CASE_ASSISTANT_TIER_CLASSIFIER_MODEL: str = os.getenv(
        "CASE_ASSISTANT_TIER_CLASSIFIER_MODEL", ""
    ).strip()
    CASE_ASSISTANT_MAX_RETRIEVAL_ROUNDS: int = int(
        os.getenv("CASE_ASSISTANT_MAX_RETRIEVAL_ROUNDS", "2") or "2"
    )
    CASE_ASSISTANT_STANDARD_MAX_RETRIEVAL_ROUNDS: int = int(
        os.getenv("CASE_ASSISTANT_STANDARD_MAX_RETRIEVAL_ROUNDS", "1") or "1"
    )
    CASE_ASSISTANT_DEEP_MAX_RETRIEVAL_ROUNDS: int = int(
        os.getenv("CASE_ASSISTANT_DEEP_MAX_RETRIEVAL_ROUNDS", "3") or "3"
    )
    # norm-only (статья/акт без материалов дела): один раунд, без case RAG
    CASE_ASSISTANT_LEGAL_NORM_ONLY_ENABLED: bool = (
        os.getenv("CASE_ASSISTANT_LEGAL_NORM_ONLY_ENABLED", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_LEGAL_NORM_MAX_RETRIEVAL_ROUNDS: int = int(
        os.getenv("CASE_ASSISTANT_LEGAL_NORM_MAX_RETRIEVAL_ROUNDS", "1") or "1"
    )
    CASE_ASSISTANT_GRAPH_RECURSION_LIMIT: int = int(
        os.getenv("CASE_ASSISTANT_GRAPH_RECURSION_LIMIT", "40") or "40"
    )
    # План retrieval (topic packs, multi-article, coverage) перед hybrid
    LEGAL_CORPUS_AGENTIC_PLAN_ENABLED: bool = (
        os.getenv("LEGAL_CORPUS_AGENTIC_PLAN_ENABLED", "true").strip().lower() == "true"
    )
    # LLM анализирует вопрос и планирует search_queries / статьи до hybrid (основной путь)
    LEGAL_CORPUS_LLM_PLANNER_ENABLED: bool = (
        os.getenv("LEGAL_CORPUS_LLM_PLANNER_ENABLED", "true").strip().lower() == "true"
    )
    LEGAL_CORPUS_LLM_PLANNER_MODEL: str = os.getenv("LEGAL_CORPUS_LLM_PLANNER_MODEL", "").strip()
    LEGAL_CORPUS_LLM_PLANNER_MAX_QUERIES: int = int(
        os.getenv("LEGAL_CORPUS_LLM_PLANNER_MAX_QUERIES", "6") or "6"
    )
    # HTTP timeout планировщика retrieval (сек); fail-open → детерминированный план
    LEGAL_CORPUS_PLANNER_TIMEOUT_SEC: float = float(
        os.getenv("LEGAL_CORPUS_PLANNER_TIMEOUT_SEC", "20") or "20"
    )
    CASE_ASSISTANT_STREAM_CASE_CHAT: bool = (
        os.getenv("CASE_ASSISTANT_STREAM_CASE_CHAT", "true").strip().lower() == "true"
    )
    # Пошаговый прогресс в UI (этап + динамические детали из фактов пайплайна).
    CASE_ASSISTANT_STREAM_ACTIVITY_UI: bool = (
        os.getenv("CASE_ASSISTANT_STREAM_ACTIVITY_UI", "true").strip().lower() == "true"
    )
    CASE_ASSISTANT_STREAM_REASONING_UI: bool = (
        os.getenv("CASE_ASSISTANT_STREAM_REASONING_UI", "false").strip().lower() == "true"
    )
    # Не блокировать SSE на commit ответа ассистента (case + global).
    ASSISTANT_ASYNC_PERSIST_ENABLED: bool = (
        os.getenv("ASSISTANT_ASYNC_PERSIST_ENABLED", "true").strip().lower() == "true"
    )
    ASSISTANT_ASYNC_PERSIST_MAX_RETRIES: int = int(
        os.getenv("ASSISTANT_ASYNC_PERSIST_MAX_RETRIES", "2") or "2"
    )
    ASSISTANT_PERSIST_WRITETHROUGH_BUFFER_ENABLED: bool = (
        os.getenv("ASSISTANT_PERSIST_WRITETHROUGH_BUFFER_ENABLED", "true").strip().lower()
        == "true"
    )
    ASSISTANT_PERSIST_WRITETHROUGH_MAX_TURNS: int = int(
        os.getenv("ASSISTANT_PERSIST_WRITETHROUGH_MAX_TURNS", "10") or "10"
    )
    # Global: отдавать status/progress во время LangGraph retrieval до генерации.
    GLOBAL_ASSISTANT_STREAM_GRAPH_PROGRESS: bool = (
        os.getenv("GLOBAL_ASSISTANT_STREAM_GRAPH_PROGRESS", "true").strip().lower() == "true"
    )

    # Draft Mode: индекс полей шаблона + заполнение (bulk по умолчанию)
    DRAFT_TEMPLATE_INDEX_ON_UPLOAD: bool = (
        os.getenv("DRAFT_TEMPLATE_INDEX_ON_UPLOAD", "true").strip().lower() == "true"
    )
    DRAFT_TEMPLATE_INDEXER_VERSION: str = os.getenv("DRAFT_TEMPLATE_INDEXER_VERSION", "3").strip()
    DRAFT_TEMPLATE_INDEX_LLM_ENRICH: bool = (
        os.getenv("DRAFT_TEMPLATE_INDEX_LLM_ENRICH", "false").strip().lower() == "true"
    )
    # Стратегия заполнения шаблона: parallel (дефолт) | bulk | per_field
    DRAFT_FILL_STRATEGY: str = os.getenv("DRAFT_FILL_STRATEGY", "parallel").strip() or "parallel"
    # Один RAG + один LLM на все поля (legacy bulk); при DRAFT_FILL_STRATEGY=bulk
    DRAFT_BULK_FILL_ENABLED: bool = (
        os.getenv("DRAFT_BULK_FILL_ENABLED", "true").strip().lower() == "true"
    )
    DRAFT_BULK_TARGETED_RETRY_ENABLED: bool = (
        os.getenv("DRAFT_BULK_TARGETED_RETRY_ENABLED", "true").strip().lower() == "true"
    )
    DRAFT_BULK_RAG_K: int = int(os.getenv("DRAFT_BULK_RAG_K", "8") or "8")
    DRAFT_BULK_RAG_STRATEGY: str = os.getenv("DRAFT_BULK_RAG_STRATEGY", "hybrid").strip() or "hybrid"
    DRAFT_BULK_CONTEXT_MAX_CHARS: int = int(os.getenv("DRAFT_BULK_CONTEXT_MAX_CHARS", "7000") or "7000")
    DRAFT_BULK_UNIFIED_MAX_FIELDS_PER_CALL: int = int(
        os.getenv("DRAFT_BULK_UNIFIED_MAX_FIELDS_PER_CALL", "48") or "48"
    )
    DRAFT_BULK_MIN_CONFIDENCE: float = float(os.getenv("DRAFT_BULK_MIN_CONFIDENCE", "0.25") or "0.25")
    DRAFT_BULK_RETRY_MAX_FIELDS: int = int(os.getenv("DRAFT_BULK_RETRY_MAX_FIELDS", "4") or "4")
    DRAFT_BULK_RETRY_MIN_SHARED_CHARS: int = int(os.getenv("DRAFT_BULK_RETRY_MIN_SHARED_CHARS", "800") or "800")
    DRAFT_BULK_RETRY_LIGHT_RAG_ENABLED: bool = (
        os.getenv("DRAFT_BULK_RETRY_LIGHT_RAG_ENABLED", "true").strip().lower() == "true"
    )
    DRAFT_BULK_RETRY_RAG_K: int = int(os.getenv("DRAFT_BULK_RETRY_RAG_K", "5") or "5")
    DRAFT_SKIP_PREFETCH_RAG_WHEN_CATALOG_FILL: bool = (
        os.getenv("DRAFT_SKIP_PREFETCH_RAG_WHEN_CATALOG_FILL", "true").strip().lower() == "true"
    )
    DRAFT_PER_FIELD_RAG_ENABLED: bool = (
        os.getenv("DRAFT_PER_FIELD_RAG_ENABLED", "true").strip().lower() == "true"
    )
    DRAFT_FIELD_FINAL_K: int = int(os.getenv("DRAFT_FIELD_FINAL_K", "5") or "5")
    DRAFT_FIELD_RAG_MAX_PARALLEL: int = int(os.getenv("DRAFT_FIELD_RAG_MAX_PARALLEL", "4") or "4")
    DRAFT_FIELD_BATCH_SIZE: int = int(os.getenv("DRAFT_FIELD_BATCH_SIZE", "8") or "8")
    DRAFT_FULL_HTML_FALLBACK_ENABLED: bool = (
        os.getenv("DRAFT_FULL_HTML_FALLBACK_ENABLED", "false").strip().lower() == "true"
    )
    DRAFT_PLAN_FIELD_PROBE_COUNT: int = int(os.getenv("DRAFT_PLAN_FIELD_PROBE_COUNT", "5") or "5")
    DRAFT_SECTION_MAX_PARALLEL: int = int(os.getenv("DRAFT_SECTION_MAX_PARALLEL", "5") or "5")
    DRAFT_LINTER_ENABLED: bool = (
        os.getenv("DRAFT_LINTER_ENABLED", "true").strip().lower() == "true"
    )
    DRAFT_SCRATCH_LLM_BLUEPRINT: bool = (
        os.getenv("DRAFT_SCRATCH_LLM_BLUEPRINT", "true").strip().lower() == "true"
    )
    DRAFT_FINANCIAL_CALCULATOR_ENABLED: bool = (
        os.getenv("DRAFT_FINANCIAL_CALCULATOR_ENABLED", "true").strip().lower() == "true"
    )
    # Автоматический калькулятор перед заполнением полей шаблона (catalog_fill / docxtpl)
    DRAFT_CATALOG_FILL_CALCULATOR_ENABLED: bool = (
        os.getenv("DRAFT_CATALOG_FILL_CALCULATOR_ENABLED", "true").strip().lower() == "true"
    )
    # unified = один LLM-проход с полным RAG (как case assistant); decomposed = legacy sections
    DRAFT_GENERATION_MODE: str = (
        os.getenv("DRAFT_GENERATION_MODE", "unified").strip().lower() or "unified"
    )
    DRAFT_UNIFIED_RAG_MAX_CHARS: int = int(
        os.getenv("DRAFT_UNIFIED_RAG_MAX_CHARS", "24000") or "24000"
    )
    DRAFT_UNIFIED_MAX_TOKENS: int = int(os.getenv("DRAFT_UNIFIED_MAX_TOKENS", "0") or "0")
    # Hybrid draft workflow: bounded gap retrieval after coverage check
    DRAFT_COVERAGE_MAX_RETRIES: int = int(os.getenv("DRAFT_COVERAGE_MAX_RETRIES", "2") or "2")
    DRAFT_COVERAGE_MAX_GAPS_PER_ROUND: int = int(
        os.getenv("DRAFT_COVERAGE_MAX_GAPS_PER_ROUND", "3") or "3"
    )
    DRAFT_COVERAGE_RETRY_RAG_K: int = int(os.getenv("DRAFT_COVERAGE_RETRY_RAG_K", "6") or "6")
    # False (default): draft mode сразу генерирует документ без отдельного плана и кнопки «Одобрить».
    DRAFT_PLAN_APPROVAL_ENABLED: bool = (
        os.getenv("DRAFT_PLAN_APPROVAL_ENABLED", "false").strip().lower() == "true"
    )

    COHERE_API_KEY: str = os.getenv("COHERE_API_KEY", "").strip()
    RERANKER_BATCH_SIZE: int = int(os.getenv("RERANKER_BATCH_SIZE", "32") or "32")
    
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
    YANDEX_FOLDER_ID: str = clean_env_str(os.getenv("YANDEX_FOLDER_ID"))  # Обязательно для работы Yandex сервисов
    YANDEX_GPT_MODEL: str = os.getenv("YANDEX_GPT_MODEL", "yandexgpt-lite/latest")  # Модель по умолчанию
    # Эмбеддинги: doc — индексация чанков, query — поисковые запросы (см. Yandex AI Studio).
    YANDEX_EMBEDDING_DOC_MODEL: str = os.getenv(
        "YANDEX_EMBEDDING_DOC_MODEL", "text-search-doc/latest"
    )
    YANDEX_EMBEDDING_QUERY_MODEL: str = os.getenv(
        "YANDEX_EMBEDDING_QUERY_MODEL", "text-search-query/latest"
    )
    # Устаревший общий ключ — fallback для query, если QUERY_MODEL не задан отдельно.
    YANDEX_EMBEDDING_MODEL: str = os.getenv("YANDEX_EMBEDDING_MODEL", "text-search-query/latest")
    YANDEX_AI_STUDIO_CLASSIFIER_ID: str = os.getenv("YANDEX_AI_STUDIO_CLASSIFIER_ID", "")  # ID классификатора в Yandex AI Studio
    
    # Полные URI моделей (приоритет над короткими именами)
    # Формат: gpt://<folder-id>/yandexgpt-lite/latest или emb://<folder-id>/text-search-query/latest
    YANDEX_GPT_MODEL_URI: str = clean_env_str(os.getenv("YANDEX_GPT_MODEL_URI"))
    YANDEX_EMBEDDING_MODEL_URI: str = clean_env_str(os.getenv("YANDEX_EMBEDDING_MODEL_URI"))
    YANDEX_EMBEDDING_DOC_MODEL_URI: str = clean_env_str(os.getenv("YANDEX_EMBEDDING_DOC_MODEL_URI"))
    YANDEX_EMBEDDING_QUERY_MODEL_URI: str = clean_env_str(os.getenv("YANDEX_EMBEDDING_QUERY_MODEL_URI"))
    YANDEX_LLM_TRANSPORT: str = clean_env_str(os.getenv("YANDEX_LLM_TRANSPORT"), "grpc").lower()
    # Классификатор документов (Yandex AI Studio). Если пусто — используем YANDEX_AI_STUDIO_CLASSIFIER_ID или LLM fallback.
    YANDEX_CLASSIFIER_MODEL_URI: str = os.getenv("YANDEX_CLASSIFIER_MODEL_URI", "")
    # SSE global-chat: отдавать клиенту reasoning-дельты из streaming chunks (если модель их присылает).
    YANDEX_SSE_STREAM_MODEL_REASONING: bool = (
        os.getenv("YANDEX_SSE_STREAM_MODEL_REASONING", "false").strip().lower() == "true"
    )

    # Embeddings transport:
    # - "openai": HTTPS OpenAI-compatible endpoint (ai.api.cloud.yandex.net) — fastest/most stable in dev/VPN/proxy envs
    # - "grpc": official YCloudML gRPC transport (may fail/hang on DNS/service discovery in some networks)
    YANDEX_EMBEDDINGS_TRANSPORT: str = clean_env_str(os.getenv("YANDEX_EMBEDDINGS_TRANSPORT"), "openai").lower()
    # Yandex embedding API лимит ~2048 tokens; длиннее — режем на части и усредняем векторы.
    YANDEX_EMBEDDING_MAX_INPUT_CHARS: int = int(os.getenv("YANDEX_EMBEDDING_MAX_INPUT_CHARS", "2800"))
    # Жёсткий потолок API (токены); рабочий лимит = min(это * ratio, MAX_INPUT_TOKENS если задан).
    YANDEX_EMBEDDING_API_TOKEN_CAP: int = int(os.getenv("YANDEX_EMBEDDING_API_TOKEN_CAP", "2048") or "2048")
    # Доля от API cap для cl100k_base-оценки (буфер под другой BPE Яндекса / кириллицу). 0.85 ≈ 15% запас.
    YANDEX_EMBEDDING_TOKEN_SAFETY_RATIO: float = float(
        os.getenv("YANDEX_EMBEDDING_TOKEN_SAFETY_RATIO", "0.85") or "0.85"
    )
    # Явный потолок токенов на один запрос эмбеддинга (0 = только ratio*cap).
    YANDEX_EMBEDDING_MAX_INPUT_TOKENS: int = int(os.getenv("YANDEX_EMBEDDING_MAX_INPUT_TOKENS", "0") or "0")
    # Нахлест символов между соседними сегментами при токен-нарезке (усреднение векторов).
    YANDEX_EMBEDDING_SEGMENT_OVERLAP_CHARS: int = int(
        os.getenv("YANDEX_EMBEDDING_SEGMENT_OVERLAP_CHARS", "150") or "150"
    )
    # OpenAI-compat: один текст на запрос; time-window micro-batching (см. yandex_embedding_http).
    YANDEX_EMBEDDING_RPS_LIMIT: int = int(os.getenv("YANDEX_EMBEDDING_RPS_LIMIT", "10") or "10")
    # gRPC-only: параллель одиночных вызовов SDK (HTTP path uses RPS_LIMIT above).
    YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS: int = int(
        os.getenv("YANDEX_EMBEDDING_MAX_PARALLEL_REQUESTS")
        or os.getenv("YANDEX_EMBEDDING_BATCH_SIZE", "8")
        or "8"
    )
    YANDEX_EMBEDDING_MIN_REQUEST_INTERVAL_SEC: float = float(
        os.getenv("YANDEX_EMBEDDING_MIN_REQUEST_INTERVAL_SEC", "0.11") or "0.11"
    )
    # Deprecated alias — не batch API; для gRPC parallel fallback.
    YANDEX_EMBEDDING_BATCH_SIZE: int = int(os.getenv("YANDEX_EMBEDDING_BATCH_SIZE", "8") or "8")

    # GigaChat (Сбер) - с поддержкой function calling
    GIGACHAT_CREDENTIALS: str = clean_env_str(os.getenv("GIGACHAT_CREDENTIALS", ""))  # Authorization Key (base64 ClientID:ClientSecret)
    # GigaChat SmartSpeech STT (separate API key for speech recognition)
    GIGACHAT_STT_CREDENTIALS: str = os.getenv("GIGACHAT_STT_CREDENTIALS", "MDE5ZDFhNmQtZWI3Yy03YTQ3LWIwMmMtNDFiZTU0ZGQ2YzU1OjQxZTEzMTMzLWEzMzUtNDNmZC05NjVmLTMyZTEwNDIwNDhjNQ==")
    GIGACHAT_MODEL: str = os.getenv("GIGACHAT_MODEL", "GigaChat-Pro")
    # По умолчанию отключаем проверку SSL для совместимости с некоторыми окружениями (Render, прокси)
    # Установите GIGACHAT_VERIFY_SSL=true для включения проверки SSL (более безопасно)
    GIGACHAT_VERIFY_SSL: bool = os.getenv("GIGACHAT_VERIFY_SSL", "false").lower() == "true"
    GIGACHAT_SCOPE: str = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")  # Scope для получения токена (GIGACHAT_API_PERS для физических лиц)
    
    # GigaChat Model Selection (Lite/Pro)
    GIGACHAT_LITE_MODEL: str = os.getenv("GIGACHAT_LITE_MODEL", "GigaChat-Lite")
    GIGACHAT_PRO_MODEL: str = os.getenv("GIGACHAT_PRO_MODEL", "GigaChat-Pro")
    MODEL_SELECTION_ENABLED: bool = os.getenv("MODEL_SELECTION_ENABLED", "true").lower() == "true"
    
    # Выбор LLM провайдера для агентов (только gigachat)
    LLM_PROVIDER: str = clean_env_str(os.getenv("LLM_PROVIDER"), "gigachat").lower()
    # Yandex Index prefix - removed (Yandex Vector Store no longer used)
    # YANDEX_INDEX_PREFIX: str = os.getenv("YANDEX_INDEX_PREFIX", "legal_ai_vault")
    
    # LangSmith (LangChain monitoring and compliance)
    LANGSMITH_API_KEY: str = os.getenv("LANGSMITH_API_KEY", "")
    LANGSMITH_PROJECT: str = os.getenv("LANGSMITH_PROJECT", "legal-ai-vault")
    LANGSMITH_TRACING: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGSMITH_ENDPOINT: str = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")

    # Langfuse (LLM observability)
    LANGFUSE_ENABLED: bool = clean_env_str(os.getenv("LANGFUSE_ENABLED"), "false").lower() == "true"
    LANGFUSE_PUBLIC_KEY: str = clean_env_str(os.getenv("LANGFUSE_PUBLIC_KEY"))
    LANGFUSE_SECRET_KEY: str = clean_env_str(os.getenv("LANGFUSE_SECRET_KEY"))
    LANGFUSE_HOST: str = clean_env_str(os.getenv("LANGFUSE_HOST")).rstrip("/")
    LANGFUSE_SAMPLE_RATE: float = float(
        (os.getenv("LANGFUSE_SAMPLE_RATE", "1.0") or "1.0").strip().strip('"').strip("'") or "1.0"
    )
    LANGFUSE_DEBUG: bool = clean_env_str(os.getenv("LANGFUSE_DEBUG"), "false").lower() == "true"
    LANGFUSE_FLUSH_ON_END: bool = clean_env_str(os.getenv("LANGFUSE_FLUSH_ON_END"), "true").lower() == "true"
    
    # File Storage
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    # When false (default), uploads write only to UPLOAD_DIR; Postgres file_content stays NULL.
    # Set true if API and worker do not share UPLOAD_DIR (no shared volume / object storage).
    FILE_STORE_BYTES_IN_DB: bool = (
        os.getenv("FILE_STORE_BYTES_IN_DB", "false").strip().lower() in ("1", "true", "yes")
    )
    # Google Drive Picker import (frontend supplies short-lived OAuth token per request)
    GOOGLE_DRIVE_IMPORT_MAX_FILES: int = int(
        os.getenv("GOOGLE_DRIVE_IMPORT_MAX_FILES", "30") or "30"
    )

    # Security / JWT
    SECRET_KEY: str = clean_env_str(
        os.getenv("SECRET_KEY"),
        "your-secret-key-here-change-in-production",
    )
    JWT_SECRET_KEY: str = clean_env_str(
        os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY"),
        "your-secret-key-change-in-production",
    )
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ALGORITHM: str = "HS256"  # Alias for JWT_ALGORITHM
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours
    # Public self-registration via POST /api/auth/register (off by default).
    AUTH_PUBLIC_REGISTRATION_ENABLED: bool = (
        os.getenv("AUTH_PUBLIC_REGISTRATION_ENABLED", "false").strip().lower() == "true"
    )
    
    # Redis for Caching and Presence (Phase 4.1)
    REDIS_URL: Optional[str] = os.getenv("REDIS_URL", None)
    PRESENCE_TTL_SECONDS: int = int(os.getenv("PRESENCE_TTL_SECONDS", "60"))  # TTL for user presence in seconds
    
    # LangGraph Postgres Checkpointer Pool Settings
    LANGGRAPH_POSTGRES_POOL_MAX_SIZE: int = int(os.getenv("LANGGRAPH_POSTGRES_POOL_MAX_SIZE", "20"))  # Max connections in pool

    # Deep agent runs (Legora-style orchestration)
    AGENT_RUNS_ENABLED: bool = os.getenv("AGENT_RUNS_ENABLED", "true").lower() == "true"
    AGENT_RUNS_CHECKPOINTER_ENABLED: bool = os.getenv(
        "AGENT_RUNS_CHECKPOINTER_ENABLED", "true"
    ).lower() == "true"
    AGENT_RUNS_RECURSION_LIMIT: int = int(os.getenv("AGENT_RUNS_RECURSION_LIMIT", "50") or "50")
    AGENT_RUNS_TOOL_CALL_RUN_LIMIT: int = int(os.getenv("AGENT_RUNS_TOOL_CALL_RUN_LIMIT", "32") or "32")
    AGENT_RUNS_MODEL_CALL_RUN_LIMIT: int = int(os.getenv("AGENT_RUNS_MODEL_CALL_RUN_LIMIT", "48") or "48")
    AGENT_RUNS_TOOL_TIMEOUT_SEC: float = float(os.getenv("AGENT_RUNS_TOOL_TIMEOUT_SEC", "120") or "120")
    AGENT_RUNS_INTERRUPT_ON_TOOLS: str = os.getenv("AGENT_RUNS_INTERRUPT_ON_TOOLS", "")
    AGENT_RUNS_SYSTEM_PROMPT: str = os.getenv("AGENT_RUNS_SYSTEM_PROMPT", "")
    AGENT_RUNS_WORKER_ENABLED: bool = os.getenv("AGENT_RUNS_WORKER_ENABLED", "true").lower() == "true"
    AGENT_RUNS_WORKER_POLL_SEC: float = float(os.getenv("AGENT_RUNS_WORKER_POLL_SEC", "0.5") or "0.5")
    AGENT_RUNS_SSE_IDLE_SEC: float = float(os.getenv("AGENT_RUNS_SSE_IDLE_SEC", "600") or "600")
    AGENT_RUNS_DRAFT_TOOL_ENABLED: bool = os.getenv("AGENT_RUNS_DRAFT_TOOL_ENABLED", "true").lower() == "true"
    AGENT_RUNS_DRAFT_TOOL_TIMEOUT_SEC: float = float(
        os.getenv("AGENT_RUNS_DRAFT_TOOL_TIMEOUT_SEC", "900") or "900"
    )


# Create config instance
config = Config()


def is_legal_corpus_force_enabled() -> bool:
    """Читает LEGAL_CORPUS_FORCE_ENABLED из конфига (legacy).

    Маршруты assistant_chat_v2 больше не подмешивают справочник по этому флагу — только UI.
    Функция оставлена для скриптов и обратной совместимости.
    """
    try:
        return bool(config.LEGAL_CORPUS_FORCE_ENABLED)
    except AttributeError:
        return os.getenv("LEGAL_CORPUS_FORCE_ENABLED", "false").strip().lower() == "true"


# Validate DATABASE_URL on module import
# #region agent log
try:
    # Never log DATABASE_URL preview: it may contain credentials.
    _debug_log(
        "config.py:322",
        "Before DATABASE_URL validation",
        {"step": "before_validation", "db_url_set": bool(os.getenv("DATABASE_URL"))},
    )
except: pass
# #endregion
try:
    Config._validate_database_url()
    # #region agent log
    try:
        _debug_log("config.py:293", "DATABASE_URL validation succeeded", {"step": "validation_success"})
    except: pass
    # #endregion
except ValueError as e:
    # #region agent log
    try:
        _debug_log("config.py:296", "DATABASE_URL validation failed", {"step": "validation_failed", "error": str(e), "error_type": type(e).__name__})
    except: pass
    # #endregion
    # In production, we want to fail fast if DATABASE_URL is not set
    import sys
    # Print error message multiple times to ensure it's visible
    error_msg = f"\n{'='*80}\n❌ DATABASE_URL VALIDATION FAILED\n{'='*80}\n{str(e)}\n{'='*80}\n"
    for _ in range(3):  # Print 3 times to ensure visibility
        print(error_msg, file=sys.stderr, flush=True)
    # Also print to stdout (some platforms capture stdout)
    for _ in range(3):
        print(error_msg, file=sys.stdout, flush=True)
    sys.exit(1)
