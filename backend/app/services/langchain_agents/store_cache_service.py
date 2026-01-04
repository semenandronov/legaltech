"""Store-based Cache Service - Phase 1.2 Implementation

This module provides PostgreSQL-based caching for agent results,
replacing the in-memory ResultCache with persistent storage.

Features:
- Persistent cache using PostgresStore / langgraph_store table
- TTL support for cache expiration
- Semantic cache via pgvector (optional)
- Query + prompt_version + agent_name based keys
- Case-level and global namespaces
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

# Cache namespace constants
NAMESPACE_AGENT_RESULTS = "agent_results"
NAMESPACE_RAG_CACHE = "rag_cache"
NAMESPACE_SEMANTIC_CACHE = "semantic_cache"


class StoreCacheService:
    """
    PostgreSQL-based cache service for agent results.
    
    Replaces the in-memory ResultCache with persistent storage
    using the langgraph_store table.
    
    Key format: hash(query + prompt_version + agent_name + case_id)
    Namespace: agent_results / case_id:agent_results
    """
    
    def __init__(
        self,
        db: Session,
        default_ttl_seconds: int = 3600,
        enable_semantic_cache: bool = False
    ):
        """
        Initialize the store cache service.
        
        Args:
            db: Database session
            default_ttl_seconds: Default TTL for cache entries (1 hour)
            enable_semantic_cache: Whether to use semantic similarity for cache lookup
        """
        self.db = db
        self.default_ttl = default_ttl_seconds
        self.enable_semantic_cache = enable_semantic_cache
        self._ensure_cache_table()
        logger.info(f"✅ StoreCacheService initialized (ttl={default_ttl_seconds}s, semantic={enable_semantic_cache})")
    
    def _ensure_cache_table(self) -> None:
        """Ensure the cache table exists with proper indexes."""
        try:
            # Add TTL column to langgraph_store if it doesn't exist
            self.db.execute(text("""
                ALTER TABLE langgraph_store 
                ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP
            """))
            
            # Add index on expires_at for efficient TTL cleanup
            self.db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_store_expires_at 
                ON langgraph_store(expires_at)
                WHERE expires_at IS NOT NULL
            """))
            
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.warning(f"Cache table enhancement may already exist: {e}")
    
    def _make_key(
        self,
        query: str,
        agent_name: str,
        prompt_version: str = "v1",
        case_id: Optional[str] = None,
        document_hash: Optional[str] = None
    ) -> str:
        """
        Create a unique cache key from query parameters.
        
        Args:
            query: The query or input text
            agent_name: Name of the agent
            prompt_version: Version of the prompt
            case_id: Optional case identifier
            document_hash: Optional hash of documents
            
        Returns:
            MD5 hash of the combined key components
        """
        key_data = {
            "query": query,
            "agent_name": agent_name,
            "prompt_version": prompt_version,
            "case_id": case_id,
            "document_hash": document_hash
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _get_namespace(
        self,
        agent_name: str,
        case_id: Optional[str] = None
    ) -> str:
        """
        Get the namespace for cache entries.
        
        Args:
            agent_name: Name of the agent
            case_id: Optional case identifier
            
        Returns:
            Namespace string
        """
        if case_id:
            return f"{NAMESPACE_AGENT_RESULTS}/{case_id}/{agent_name}"
        return f"{NAMESPACE_AGENT_RESULTS}/{agent_name}"
    
    def get(
        self,
        query: str,
        agent_name: str,
        case_id: Optional[str] = None,
        prompt_version: str = "v1",
        document_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached result if available and not expired.
        
        Args:
            query: The query or input text
            agent_name: Name of the agent
            case_id: Optional case identifier
            prompt_version: Version of the prompt
            document_hash: Optional document hash
            
        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(query, agent_name, prompt_version, case_id, document_hash)
        namespace = self._get_namespace(agent_name, case_id)
        
        try:
            result = self.db.execute(
                text("""
                    SELECT value, expires_at
                    FROM langgraph_store
                    WHERE namespace = :namespace AND key = :key
                """),
                {"namespace": namespace, "key": key}
            ).fetchone()
            
            if not result:
                logger.debug(f"[StoreCache] Cache miss: {agent_name}/{key[:8]}")
                return None
            
            value_data, expires_at = result
            
            # Check expiration
            if expires_at and datetime.now() > expires_at:
                logger.debug(f"[StoreCache] Cache expired: {agent_name}/{key[:8]}")
                # Optionally delete expired entry
                self._delete_entry(namespace, key)
                return None
            
            # Parse value
            if isinstance(value_data, str):
                cached_result = json.loads(value_data)
            else:
                cached_result = value_data
            
            logger.debug(f"[StoreCache] Cache hit: {agent_name}/{key[:8]}")
            return cached_result.get("result")
            
        except Exception as e:
            logger.error(f"[StoreCache] Error getting cache: {e}")
            return None
    
    def set(
        self,
        query: str,
        agent_name: str,
        result: Dict[str, Any],
        case_id: Optional[str] = None,
        prompt_version: str = "v1",
        document_hash: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Store result in cache.
        
        Args:
            query: The query or input text
            agent_name: Name of the agent
            result: Result to cache
            case_id: Optional case identifier
            prompt_version: Version of the prompt
            document_hash: Optional document hash
            ttl_seconds: Optional custom TTL
            metadata: Optional additional metadata
            
        Returns:
            True if cached successfully
        """
        key = self._make_key(query, agent_name, prompt_version, case_id, document_hash)
        namespace = self._get_namespace(agent_name, case_id)
        
        ttl = ttl_seconds or self.default_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)
        
        value_data = {
            "result": result,
            "cached_at": datetime.now().isoformat(),
            "query": query[:200],  # Store truncated query for debugging
            "prompt_version": prompt_version
        }
        
        meta = {
            "agent_name": agent_name,
            "case_id": case_id,
            "ttl_seconds": ttl,
            **(metadata or {})
        }
        
        try:
            # Upsert pattern
            self.db.execute(
                text("""
                    INSERT INTO langgraph_store (namespace, key, value, metadata, expires_at)
                    VALUES (:namespace, :key, :value, :metadata, :expires_at)
                    ON CONFLICT (namespace, key) DO UPDATE SET
                        value = EXCLUDED.value,
                        metadata = EXCLUDED.metadata,
                        expires_at = EXCLUDED.expires_at,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "namespace": namespace,
                    "key": key,
                    "value": json.dumps(value_data),
                    "metadata": json.dumps(meta),
                    "expires_at": expires_at
                }
            )
            self.db.commit()
            
            logger.debug(f"[StoreCache] Cached: {agent_name}/{key[:8]} (ttl={ttl}s)")
            return True
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"[StoreCache] Error caching: {e}")
            return False
    
    def _delete_entry(self, namespace: str, key: str) -> bool:
        """Delete a specific cache entry."""
        try:
            self.db.execute(
                text("""
                    DELETE FROM langgraph_store
                    WHERE namespace = :namespace AND key = :key
                """),
                {"namespace": namespace, "key": key}
            )
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"[StoreCache] Error deleting entry: {e}")
            return False
    
    def invalidate(
        self,
        agent_name: Optional[str] = None,
        case_id: Optional[str] = None
    ) -> int:
        """
        Invalidate cache entries.
        
        Args:
            agent_name: Optional agent name (if None, invalidates all)
            case_id: Optional case ID (if None with agent_name, invalidates all for agent)
            
        Returns:
            Number of entries invalidated
        """
        try:
            if agent_name and case_id:
                namespace = self._get_namespace(agent_name, case_id)
                result = self.db.execute(
                    text("""
                        DELETE FROM langgraph_store
                        WHERE namespace = :namespace
                    """),
                    {"namespace": namespace}
                )
            elif case_id:
                # Invalidate all agents for a case
                result = self.db.execute(
                    text("""
                        DELETE FROM langgraph_store
                        WHERE namespace LIKE :pattern
                    """),
                    {"pattern": f"{NAMESPACE_AGENT_RESULTS}/{case_id}/%"}
                )
            elif agent_name:
                # Invalidate all entries for an agent (across cases)
                result = self.db.execute(
                    text("""
                        DELETE FROM langgraph_store
                        WHERE namespace LIKE :pattern
                    """),
                    {"pattern": f"{NAMESPACE_AGENT_RESULTS}/%/{agent_name}"}
                )
            else:
                # Invalidate all cache entries
                result = self.db.execute(
                    text("""
                        DELETE FROM langgraph_store
                        WHERE namespace LIKE :pattern
                    """),
                    {"pattern": f"{NAMESPACE_AGENT_RESULTS}/%"}
                )
            
            self.db.commit()
            count = result.rowcount
            logger.info(f"[StoreCache] Invalidated {count} entries")
            return count
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"[StoreCache] Error invalidating: {e}")
            return 0
    
    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.
        
        Returns:
            Number of entries cleaned up
        """
        try:
            result = self.db.execute(
                text("""
                    DELETE FROM langgraph_store
                    WHERE expires_at IS NOT NULL
                    AND expires_at < :now
                    AND namespace LIKE :pattern
                """),
                {
                    "now": datetime.now(),
                    "pattern": f"{NAMESPACE_AGENT_RESULTS}/%"
                }
            )
            self.db.commit()
            count = result.rowcount
            
            if count > 0:
                logger.info(f"[StoreCache] Cleaned up {count} expired entries")
            
            return count
            
        except Exception as e:
            self.db.rollback()
            logger.error(f"[StoreCache] Error cleaning up: {e}")
            return 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            now = datetime.now()
            
            # Total entries
            total = self.db.execute(
                text("""
                    SELECT COUNT(*) FROM langgraph_store
                    WHERE namespace LIKE :pattern
                """),
                {"pattern": f"{NAMESPACE_AGENT_RESULTS}/%"}
            ).scalar() or 0
            
            # Expired entries
            expired = self.db.execute(
                text("""
                    SELECT COUNT(*) FROM langgraph_store
                    WHERE namespace LIKE :pattern
                    AND expires_at IS NOT NULL
                    AND expires_at < :now
                """),
                {"pattern": f"{NAMESPACE_AGENT_RESULTS}/%", "now": now}
            ).scalar() or 0
            
            # Entries by agent
            by_agent = self.db.execute(
                text("""
                    SELECT 
                        SPLIT_PART(namespace, '/', 3) as agent_name,
                        COUNT(*) as count
                    FROM langgraph_store
                    WHERE namespace LIKE :pattern
                    GROUP BY SPLIT_PART(namespace, '/', 3)
                    ORDER BY count DESC
                """),
                {"pattern": f"{NAMESPACE_AGENT_RESULTS}/%"}
            ).fetchall()
            
            return {
                "total_entries": total,
                "expired_entries": expired,
                "active_entries": total - expired,
                "default_ttl_seconds": self.default_ttl,
                "semantic_cache_enabled": self.enable_semantic_cache,
                "entries_by_agent": {row[0]: row[1] for row in by_agent if row[0]}
            }
            
        except Exception as e:
            logger.error(f"[StoreCache] Error getting stats: {e}")
            return {
                "error": str(e),
                "total_entries": 0
            }


class SemanticCacheService(StoreCacheService):
    """
    Extended cache service with semantic similarity matching.
    
    Uses pgvector embeddings to find similar queries and return
    cached results even for semantically similar (not identical) queries.
    """
    
    def __init__(
        self,
        db: Session,
        default_ttl_seconds: int = 3600,
        similarity_threshold: float = 0.85
    ):
        """
        Initialize semantic cache service.
        
        Args:
            db: Database session
            default_ttl_seconds: Default TTL for cache entries
            similarity_threshold: Minimum similarity score for cache hit
        """
        super().__init__(db, default_ttl_seconds, enable_semantic_cache=True)
        self.similarity_threshold = similarity_threshold
        self._embedding_service = None
        logger.info(f"✅ SemanticCacheService initialized (threshold={similarity_threshold})")
    
    def _get_embedding_service(self):
        """Lazy load embedding service."""
        if self._embedding_service is None:
            try:
                from app.services.embedding_service import get_embedding_service
                self._embedding_service = get_embedding_service()
            except ImportError:
                logger.warning("Embedding service not available for semantic cache")
        return self._embedding_service
    
    def get_similar(
        self,
        query: str,
        agent_name: str,
        case_id: Optional[str] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find similar cached queries using semantic search.
        
        Args:
            query: The query to find similar entries for
            agent_name: Name of the agent
            case_id: Optional case identifier
            limit: Maximum number of similar results
            
        Returns:
            List of similar cached results with similarity scores
        """
        embedding_service = self._get_embedding_service()
        if not embedding_service:
            return []
        
        try:
            # Get embedding for query
            query_embedding = embedding_service.embed_query(query)
            
            namespace = self._get_namespace(agent_name, case_id)
            
            # Search for similar in pgvector
            # Note: This assumes embeddings are stored in the value JSONB
            results = self.db.execute(
                text("""
                    SELECT 
                        key,
                        value,
                        1 - (value->>'embedding')::vector <=> :embedding::vector as similarity
                    FROM langgraph_store
                    WHERE namespace = :namespace
                    AND (expires_at IS NULL OR expires_at > :now)
                    AND value->>'embedding' IS NOT NULL
                    ORDER BY (value->>'embedding')::vector <=> :embedding::vector
                    LIMIT :limit
                """),
                {
                    "namespace": namespace,
                    "embedding": str(query_embedding),
                    "now": datetime.now(),
                    "limit": limit
                }
            ).fetchall()
            
            similar = []
            for row in results:
                key, value_data, similarity = row
                if similarity >= self.similarity_threshold:
                    value = json.loads(value_data) if isinstance(value_data, str) else value_data
                    similar.append({
                        "key": key,
                        "result": value.get("result"),
                        "similarity": float(similarity),
                        "cached_query": value.get("query")
                    })
            
            return similar
            
        except Exception as e:
            logger.error(f"[SemanticCache] Error finding similar: {e}")
            return []


# Global service instances
_store_cache_service: Optional[StoreCacheService] = None


def get_store_cache_service(db: Session) -> StoreCacheService:
    """
    Get or create the store cache service.
    
    Args:
        db: Database session
        
    Returns:
        StoreCacheService instance
    """
    global _store_cache_service
    
    if _store_cache_service is None:
        from app.config import config
        
        ttl = getattr(config, 'CACHE_TTL_SECONDS', 3600)
        enable_semantic = getattr(config, 'CACHE_SEMANTIC_ENABLED', False)
        
        _store_cache_service = StoreCacheService(
            db=db,
            default_ttl_seconds=ttl,
            enable_semantic_cache=enable_semantic
        )
    
    return _store_cache_service


# Backward compatibility wrapper
def get_result_cache_compat(db: Session) -> StoreCacheService:
    """
    Compatibility wrapper to replace get_result_cache().
    
    Args:
        db: Database session
        
    Returns:
        StoreCacheService that mimics ResultCache interface
    """
    return get_store_cache_service(db)

