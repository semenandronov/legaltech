"""Batch RAG Service for parallel document retrieval

Provides batch/parallel search capabilities for RAG to optimize
performance when multiple queries need to be executed.
"""
from typing import List, Optional, Dict, Any
from langchain_core.documents import Document
from app.services.rag_service import RAGService
import asyncio
import logging
import hashlib
import json

logger = logging.getLogger(__name__)


class BatchRAGService:
    """
    Обёртка для батчевых вызовов RAG.
    
    Поддерживает параллельный поиск по нескольким запросам
    и кэширование результатов для оптимизации.
    """
    
    def __init__(self, rag_service: RAGService, enable_cache: bool = True):
        """
        Initialize batch RAG service.
        
        Args:
            rag_service: RAG service instance
            enable_cache: Enable caching of search results
        """
        self.rag_service = rag_service
        self.enable_cache = enable_cache
        self._cache: Dict[str, List[Document]] = {}
    
    def _make_cache_key(self, query: str, case_id: str, k: int = 20) -> str:
        """Create cache key for query"""
        key_data = f"{case_id}:{query}:{k}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    async def batch_search(
        self,
        queries: List[str],
        case_id: str,
        k: int = 20,
        db=None
    ) -> List[List[Document]]:
        """
        Параллельный поиск по нескольким запросам.
        
        Args:
            queries: List of search queries
            case_id: Case identifier
            k: Number of documents to retrieve per query
            db: Optional database session
        
        Returns:
            List of document lists (one per query)
        """
        if not queries:
            return []
        
        logger.debug(f"[BatchRAG] Executing {len(queries)} queries in parallel for case {case_id}")
        
        # Create tasks for parallel execution
        tasks = []
        for query in queries:
            if self.enable_cache:
                cache_key = self._make_cache_key(query, case_id, k)
                if cache_key in self._cache:
                    logger.debug(f"[BatchRAG] Cache hit for query: {query[:50]}...")
                    # Return cached result as completed future
                    cached_result = self._cache[cache_key]
                    tasks.append(asyncio.create_task(self._cached_result(cached_result)))
                    continue
            
            # Create search task
            task = self._search_task(query, case_id, k, db, cache_key if self.enable_cache else None)
            tasks.append(task)
        
        # Execute all tasks in parallel
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Handle exceptions
            final_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"[BatchRAG] Query {i} failed: {result}")
                    final_results.append([])
                else:
                    final_results.append(result)
            
            logger.debug(f"[BatchRAG] Completed {len(final_results)} queries")
            return final_results
            
        except Exception as e:
            logger.error(f"[BatchRAG] Error in batch search: {e}", exc_info=True)
            # Fallback: return empty results
            return [[] for _ in queries]
    
    async def _cached_result(self, cached_docs: List[Document]) -> List[Document]:
        """Helper to return cached result as async"""
        return cached_docs
    
    async def _search_task(
        self,
        query: str,
        case_id: str,
        k: int,
        db,
        cache_key: Optional[str]
    ) -> List[Document]:
        """
        Async wrapper for RAG search.
        
        Args:
            query: Search query
            case_id: Case identifier
            k: Number of documents
            db: Optional database session
            cache_key: Optional cache key for storing result
        
        Returns:
            List of documents
        """
        try:
            # Run search in thread pool (RAG service is likely sync)
            loop = asyncio.get_event_loop()
            docs = await loop.run_in_executor(
                None,
                lambda: self.rag_service.retrieve_context(case_id, query, k=k, db=db)
            )
            
            # Cache result if enabled
            if self.enable_cache and cache_key:
                self._cache[cache_key] = docs
            
            return docs
            
        except Exception as e:
            logger.error(f"[BatchRAG] Error in search task for query '{query[:50]}...': {e}")
            return []
    
    def cached_search(
        self,
        query: str,
        case_id: str,
        k: int = 20,
        db=None
    ) -> List[Document]:
        """
        Поиск с кэшированием результатов (synchronous).
        
        Args:
            query: Search query
            case_id: Case identifier
            k: Number of documents
            db: Optional database session
        
        Returns:
            List of documents
        """
        if self.enable_cache:
            cache_key = self._make_cache_key(query, case_id, k)
            if cache_key in self._cache:
                logger.debug(f"[BatchRAG] Cache hit for query: {query[:50]}...")
                return self._cache[cache_key]
        
        # Execute search
        try:
            docs = self.rag_service.retrieve_context(case_id, query, k=k, db=db)
            
            # Cache result
            if self.enable_cache:
                cache_key = self._make_cache_key(query, case_id, k)
                self._cache[cache_key] = docs
            
            return docs
            
        except Exception as e:
            logger.error(f"[BatchRAG] Error in cached search: {e}")
            return []
    
    def clear_cache(self):
        """Clear search cache"""
        self._cache.clear()
        logger.debug("[BatchRAG] Cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "cached_queries": len(self._cache),
            "total_cached_docs": sum(len(docs) for docs in self._cache.values())
        }

















