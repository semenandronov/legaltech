"""RAG Cache for caching RAG query results between agents"""
from typing import Optional, List, Dict, Any
from langchain_core.documents import Document
import hashlib
import json
import time
import logging

logger = logging.getLogger(__name__)

# TTL для кэша (1 час)
CACHE_TTL_SECONDS = 3600


class RAGCache:
    """
    Кэш для результатов RAG запросов
    
    Кэширует результаты по query fingerprint:
    - query + case_id + k (количество документов)
    - TTL: 1 час
    - Переиспользование между агентами
    """
    
    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        """
        Инициализация RAGCache
        
        Args:
            ttl_seconds: Время жизни кэша в секундах
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds
        self.max_size = 500  # Максимум записей в кэше
    
    def _create_fingerprint(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        retrieval_strategy: Optional[str] = None,
        doc_types: Optional[List[str]] = None
    ) -> str:
        """
        Создать fingerprint запроса для кэш-ключа
        
        Args:
            case_id: ID дела
            query: Запрос
            k: Количество документов
            retrieval_strategy: Стратегия поиска
            doc_types: Типы документов
        
        Returns:
            Хеш-строка fingerprint
        """
        fingerprint_data = {
            "case_id": case_id,
            "query": query.lower().strip(),  # Нормализация
            "k": k,
            "retrieval_strategy": retrieval_strategy or "simple",
            "doc_types": sorted(doc_types) if doc_types else []
        }
        
        # Создать хеш
        fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
        fingerprint_hash = hashlib.md5(fingerprint_str.encode()).hexdigest()
        
        return fingerprint_hash
    
    def get(
        self,
        case_id: str,
        query: str,
        k: int = 5,
        retrieval_strategy: Optional[str] = None,
        doc_types: Optional[List[str]] = None
    ) -> Optional[List[Document]]:
        """
        Получить закэшированные результаты RAG
        
        Args:
            case_id: ID дела
            query: Запрос
            k: Количество документов
            retrieval_strategy: Стратегия поиска
            doc_types: Типы документов
        
        Returns:
            Список документов или None если не найдено/истекло
        """
        fingerprint = self._create_fingerprint(
            case_id, query, k, retrieval_strategy, doc_types
        )
        
        if fingerprint not in self.cache:
            return None
        
        cache_entry = self.cache[fingerprint]
        
        # Проверить TTL
        if time.time() - cache_entry["timestamp"] > self.ttl:
            # Удалить устаревшую запись
            del self.cache[fingerprint]
            logger.debug(f"[RAGCache] Cache entry expired: {fingerprint[:8]}")
            return None
        
        # Восстановить документы из кэша
        documents_data = cache_entry["documents"]
        documents = self._deserialize_documents(documents_data)
        
        logger.debug(f"[RAGCache] Cache hit: {fingerprint[:8]} → {len(documents)} documents")
        return documents
    
    def set(
        self,
        case_id: str,
        query: str,
        documents: List[Document],
        k: int = 5,
        retrieval_strategy: Optional[str] = None,
        doc_types: Optional[List[str]] = None
    ) -> None:
        """
        Сохранить результаты RAG в кэш
        
        Args:
            case_id: ID дела
            query: Запрос
            documents: Список документов
            k: Количество документов
            retrieval_strategy: Стратегия поиска
            doc_types: Типы документов
        """
        fingerprint = self._create_fingerprint(
            case_id, query, k, retrieval_strategy, doc_types
        )
        
        # Очистка устаревших записей если кэш переполнен
        if len(self.cache) >= self.max_size:
            self._cleanup_expired()
        
        # Если все еще переполнен, удалить самые старые
        if len(self.cache) >= self.max_size:
            # Найти самую старую запись
            oldest_fingerprint = min(
                self.cache.keys(),
                key=lambda k: self.cache[k]["timestamp"]
            )
            del self.cache[oldest_fingerprint]
            logger.debug(f"[RAGCache] Evicted oldest entry: {oldest_fingerprint[:8]}")
        
        # Сериализовать документы
        documents_data = self._serialize_documents(documents)
        
        # Сохранить новую запись
        self.cache[fingerprint] = {
            "documents": documents_data,
            "timestamp": time.time(),
            "case_id": case_id,
            "query": query[:100]  # Для логирования
        }
        
        logger.debug(f"[RAGCache] Cached RAG result: {fingerprint[:8]} → {len(documents)} documents")
    
    def _serialize_documents(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        Сериализовать документы для хранения в кэше
        
        Args:
            documents: Список документов
        
        Returns:
            Список словарей с данными документов
        """
        return [
            {
                "page_content": doc.page_content,
                "metadata": doc.metadata
            }
            for doc in documents
        ]
    
    def _deserialize_documents(self, documents_data: List[Dict[str, Any]]) -> List[Document]:
        """
        Десериализовать документы из кэша
        
        Args:
            documents_data: Список словарей с данными документов
        
        Returns:
            Список документов
        """
        return [
            Document(
                page_content=doc_data["page_content"],
                metadata=doc_data.get("metadata", {})
            )
            for doc_data in documents_data
        ]
    
    def _cleanup_expired(self) -> None:
        """Удалить устаревшие записи из кэша"""
        current_time = time.time()
        expired_keys = [
            key for key, entry in self.cache.items()
            if current_time - entry["timestamp"] > self.ttl
        ]
        
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.debug(f"[RAGCache] Cleaned up {len(expired_keys)} expired entries")
    
    def clear(self) -> None:
        """Очистить весь кэш"""
        self.cache.clear()
        logger.info("[RAGCache] Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получить статистику кэша
        
        Returns:
            Словарь со статистикой
        """
        current_time = time.time()
        valid_entries = sum(
            1 for entry in self.cache.values()
            if current_time - entry["timestamp"] <= self.ttl
        )
        
        return {
            "total_entries": len(self.cache),
            "valid_entries": valid_entries,
            "expired_entries": len(self.cache) - valid_entries,
            "max_size": self.max_size,
            "ttl_seconds": self.ttl
        }


# Глобальный экземпляр
_rag_cache = None


def get_rag_cache() -> RAGCache:
    """Получить глобальный экземпляр RAGCache"""
    global _rag_cache
    if _rag_cache is None:
        _rag_cache = RAGCache()
    return _rag_cache




























