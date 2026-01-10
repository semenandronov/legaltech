"""Result cache for agent results to avoid redundant computation"""
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class ResultCache:
    """
    Cache for agent results to avoid redundant computation.
    
    Uses case_id + agent_name + document_hash as cache key.
    Cache entries expire after TTL (default: 1 hour).
    """
    
    def __init__(self, default_ttl_seconds: int = 3600, max_size: int = 1000):
        """
        Initialize result cache
        
        Args:
            default_ttl_seconds: Default time-to-live for cache entries (1 hour)
            max_size: Maximum number of cache entries (LRU eviction)
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl_seconds
        self.max_size = max_size
        self.access_order: list[str] = []  # For LRU eviction
    
    def _make_key(self, case_id: str, agent_name: str, document_hash: Optional[str] = None) -> str:
        """
        Create cache key from case_id, agent_name, and optional document hash
        
        Args:
            case_id: Case identifier
            agent_name: Agent name
            document_hash: Optional hash of documents (for invalidation on document change)
            
        Returns:
            Cache key string
        """
        key_data = {
            "case_id": case_id,
            "agent_name": agent_name,
            "document_hash": document_hash
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Check if cache entry is expired"""
        expires_at = entry.get("expires_at")
        if not expires_at:
            return True
        return datetime.now() > datetime.fromisoformat(expires_at)
    
    def get(
        self,
        case_id: str,
        agent_name: str,
        document_hash: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get cached result if available and not expired
        
        Args:
            case_id: Case identifier
            agent_name: Agent name
            document_hash: Optional document hash for validation
            
        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(case_id, agent_name, document_hash)
        
        if key not in self.cache:
            logger.debug(f"[ResultCache] Cache miss for {agent_name} in case {case_id}")
            return None
        
        entry = self.cache[key]
        
        # Check expiration
        if self._is_expired(entry):
            logger.debug(f"[ResultCache] Cache entry expired for {agent_name} in case {case_id}")
            del self.cache[key]
            if key in self.access_order:
                self.access_order.remove(key)
            return None
        
        # Update access order (LRU)
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
        
        logger.debug(f"[ResultCache] Cache hit for {agent_name} in case {case_id}")
        return entry.get("result")
    
    def set(
        self,
        case_id: str,
        agent_name: str,
        result: Dict[str, Any],
        document_hash: Optional[str] = None,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Store result in cache
        
        Args:
            case_id: Case identifier
            agent_name: Agent name
            result: Result to cache
            document_hash: Optional document hash
            ttl_seconds: Optional custom TTL (defaults to default_ttl)
        """
        key = self._make_key(case_id, agent_name, document_hash)
        ttl = ttl_seconds or self.default_ttl
        expires_at = (datetime.now() + timedelta(seconds=ttl)).isoformat()
        
        # LRU eviction if cache is full
        if len(self.cache) >= self.max_size and key not in self.cache:
            oldest_key = self.access_order.pop(0)
            del self.cache[oldest_key]
            logger.debug(f"[ResultCache] Evicted oldest entry: {oldest_key[:8]}")
        
        self.cache[key] = {
            "result": result,
            "expires_at": expires_at,
            "cached_at": datetime.now().isoformat(),
            "agent_name": agent_name,
            "case_id": case_id
        }
        
        # Update access order
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
        
        logger.debug(f"[ResultCache] Cached result for {agent_name} in case {case_id}")
    
    def invalidate(self, case_id: str, agent_name: Optional[str] = None) -> int:
        """
        Invalidate cache entries for a case (and optionally specific agent)
        
        Args:
            case_id: Case identifier
            agent_name: Optional agent name (if None, invalidates all agents for case)
            
        Returns:
            Number of entries invalidated
        """
        keys_to_remove = []
        for key, entry in self.cache.items():
            if entry.get("case_id") == case_id:
                if agent_name is None or entry.get("agent_name") == agent_name:
                    keys_to_remove.append(key)
        
        for key in keys_to_remove:
            del self.cache[key]
            if key in self.access_order:
                self.access_order.remove(key)
        
        count = len(keys_to_remove)
        if count > 0:
            logger.info(f"[ResultCache] Invalidated {count} entries for case {case_id}" + 
                       (f", agent {agent_name}" if agent_name else ""))
        
        return count
    
    def clear(self) -> None:
        """Clear all cache entries"""
        count = len(self.cache)
        self.cache.clear()
        self.access_order.clear()
        logger.info(f"[ResultCache] Cleared {count} cache entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        expired_count = sum(1 for entry in self.cache.values() if self._is_expired(entry))
        
        return {
            "total_entries": len(self.cache),
            "expired_entries": expired_count,
            "active_entries": len(self.cache) - expired_count,
            "max_size": self.max_size,
            "default_ttl_seconds": self.default_ttl
        }


# Global cache instance
_global_cache: Optional[ResultCache] = None


def get_result_cache() -> ResultCache:
    """Get or create global result cache instance"""
    global _global_cache
    if _global_cache is None:
        _global_cache = ResultCache()
    return _global_cache


















