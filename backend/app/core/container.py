"""
Dependency Injection Container

Централизованное управление зависимостями приложения.
Обеспечивает:
- Singleton для тяжёлых сервисов (RAG, DocumentProcessor)
- Factory для лёгких сервисов (ChatOrchestrator, HistoryService)
- Простое тестирование через подмену зависимостей
"""
from typing import Optional, Dict, Any
from functools import lru_cache
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)


class Container:
    """
    DI контейнер для управления зависимостями.
    
    Использует lazy initialization для тяжёлых сервисов.
    """
    
    _instance: Optional["Container"] = None
    
    def __init__(self):
        """Инициализация контейнера"""
        self._rag_service = None
        self._document_processor = None
        self._cache_manager = None
        self._llm = None
        
        # Переопределения для тестов
        self._overrides: Dict[str, Any] = {}
        
        logger.info("Container initialized")
    
    @classmethod
    def get_instance(cls) -> "Container":
        """Получить singleton instance контейнера"""
        if cls._instance is None:
            cls._instance = Container()
        return cls._instance
    
    @classmethod
    def reset(cls) -> None:
        """Сбросить контейнер (для тестов)"""
        cls._instance = None
    
    def override(self, key: str, value: Any) -> None:
        """
        Переопределить зависимость (для тестов)
        
        Args:
            key: Имя зависимости
            value: Значение для подмены
        """
        self._overrides[key] = value
        logger.debug(f"Override set: {key}")
    
    def clear_overrides(self) -> None:
        """Очистить все переопределения"""
        self._overrides.clear()
    
    # =========================================================================
    # Singleton сервисы (тяжёлые, инициализируются один раз)
    # =========================================================================
    
    @property
    def rag_service(self):
        """Получить RAG сервис (singleton)"""
        if "rag_service" in self._overrides:
            return self._overrides["rag_service"]
        
        if self._rag_service is None:
            from app.services.rag_service import RAGService
            self._rag_service = RAGService()
            logger.info("RAGService initialized")
        
        return self._rag_service
    
    @property
    def document_processor(self):
        """Получить Document Processor (singleton)"""
        if "document_processor" in self._overrides:
            return self._overrides["document_processor"]
        
        if self._document_processor is None:
            from app.services.document_processor import DocumentProcessor
            self._document_processor = DocumentProcessor()
            logger.info("DocumentProcessor initialized")
        
        return self._document_processor
    
    @property
    def cache_manager(self):
        """Получить Cache Manager (singleton)"""
        if "cache_manager" in self._overrides:
            return self._overrides["cache_manager"]
        
        if self._cache_manager is None:
            from app.services.external_sources.cache_manager import get_cache_manager
            from app.config import config
            
            redis_url = getattr(config, 'REDIS_URL', None)
            ttl = getattr(config, 'CACHE_TTL_SECONDS', 3600)
            self._cache_manager = get_cache_manager(redis_url=redis_url, default_ttl=ttl)
            logger.info("CacheManager initialized")
        
        return self._cache_manager
    
    @property
    def llm(self):
        """Получить LLM для классификации (singleton)"""
        if "llm" in self._overrides:
            return self._overrides["llm"]
        
        if self._llm is None:
            from app.services.llm_factory import create_llm
            self._llm = create_llm(temperature=0.0, max_tokens=500)
            logger.info("LLM initialized")
        
        return self._llm
    
    # =========================================================================
    # Factory методы (создают новый instance)
    # =========================================================================
    
    def create_classifier(self):
        """Создать RequestClassifier"""
        if "classifier" in self._overrides:
            return self._overrides["classifier"]
        
        from app.services.chat.classifier import RequestClassifier
        return RequestClassifier(
            llm=self.llm,
            cache=self.cache_manager
        )
    
    def create_history_service(self, db: Session):
        """
        Создать ChatHistoryService
        
        Args:
            db: SQLAlchemy сессия
        """
        if "history_service" in self._overrides:
            return self._overrides["history_service"]
        
        from app.services.chat.history_service import ChatHistoryService
        return ChatHistoryService(db)
    
    def create_chat_orchestrator(self, db: Session):
        """
        Создать ChatOrchestrator
        
        Args:
            db: SQLAlchemy сессия
        """
        if "chat_orchestrator" in self._overrides:
            return self._overrides["chat_orchestrator"]
        
        from app.services.chat.orchestrator import ChatOrchestrator
        return ChatOrchestrator(
            db=db,
            rag_service=self.rag_service,
            document_processor=self.document_processor,
            classifier=self.create_classifier()
        )
    
    def create_rag_handler(self, db: Session):
        """
        Создать RAGHandler
        
        Args:
            db: SQLAlchemy сессия
        """
        if "rag_handler" in self._overrides:
            return self._overrides["rag_handler"]
        
        from app.services.chat.rag_handler import RAGHandler
        return RAGHandler(
            rag_service=self.rag_service,
            db=db
        )
    
    def create_draft_handler(self, db: Session):
        """
        Создать DraftHandler
        
        Args:
            db: SQLAlchemy сессия
        """
        if "draft_handler" in self._overrides:
            return self._overrides["draft_handler"]
        
        from app.services.chat.draft_handler import DraftHandler
        return DraftHandler(db)
    
    def create_editor_handler(self, db: Session):
        """
        Создать EditorHandler
        
        Args:
            db: SQLAlchemy сессия
        """
        if "editor_handler" in self._overrides:
            return self._overrides["editor_handler"]
        
        from app.services.chat.editor_handler import EditorHandler
        return EditorHandler(
            rag_service=self.rag_service,
            db=db
        )


# =============================================================================
# Convenience functions для FastAPI Depends
# =============================================================================

def get_container() -> Container:
    """Получить DI контейнер"""
    return Container.get_instance()


def get_rag_service():
    """Получить RAG сервис"""
    return get_container().rag_service


def get_document_processor():
    """Получить Document Processor"""
    return get_container().document_processor


def get_classifier():
    """Получить RequestClassifier"""
    return get_container().create_classifier()


def get_chat_orchestrator(db: Session):
    """
    Получить ChatOrchestrator
    
    Args:
        db: SQLAlchemy сессия
    """
    return get_container().create_chat_orchestrator(db)


def get_history_service(db: Session):
    """
    Получить ChatHistoryService
    
    Args:
        db: SQLAlchemy сессия
    """
    return get_container().create_history_service(db)


