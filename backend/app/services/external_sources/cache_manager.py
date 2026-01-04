"""Redis cache manager for external sources"""
from typing import Optional, Any, Dict
import json
import logging
from datetime import timedelta
import hashlib

logger = logging.getLogger(__name__)

# Try to import redis, fallback to in-memory cache if not available
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using in-memory cache")


class CacheManager:
    """
    Cache manager for external source results.
    
    Uses Redis if available, otherwise falls back to in-memory cache.
    """
    
    def __init__(self, redis_url: Optional[str] = None, default_ttl: int = 3600):
        """
        Initialize cache manager
        
        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379/0")
            default_ttl: Default TTL in seconds (default: 1 hour)
        """
        self.default_ttl = default_ttl
        self._redis_client = None
        self._memory_cache: Dict[str, tuple] = {}  # key -> (value, expiry_time)
        
        if REDIS_AVAILABLE and redis_url:
            try:
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
                # Test connection
                self._redis_client.ping()
                logger.info("✅ Redis cache initialized")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}, using in-memory cache")
                self._redis_client = None
        else:
            if not REDIS_AVAILABLE:
                logger.info("Redis not installed, using in-memory cache")
            else:
                logger.info("Redis URL not provided, using in-memory cache")
    
    def _make_key(self, source_name: str, query: str, filters: Optional[Dict] = None) -> str:
        """
        Create cache key from source name, query, and filters
        
        Args:
            source_name: Name of the source
            query: Search query
            filters: Optional filters
        
        Returns:
            Cache key string
        """
        # Create deterministic key
        key_data = {
            "source": source_name,
            "query": query,
            "filters": filters or {}
        }
        key_str = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
        key_hash = hashlib.md5(key_str.encode('utf-8')).hexdigest()
        return f"external_source:{source_name}:{key_hash}"
    
    def get(self, source_name: str, query: str, filters: Optional[Dict] = None) -> Optional[Any]:
        """
        Get cached result
        
        Args:
            source_name: Name of the source
            query: Search query
            filters: Optional filters
        
        Returns:
            Cached result or None
        """
        key = self._make_key(source_name, query, filters)
        
        if self._redis_client:
            try:
                cached = self._redis_client.get(key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"Error reading from Redis cache: {e}")
        else:
            # In-memory cache
            if key in self._memory_cache:
                value, expiry = self._memory_cache[key]
                import time
                if time.time() < expiry:
                    return value
                else:
                    # Expired, remove it
                    del self._memory_cache[key]
        
        return None
    
    def set(
        self,
        source_name: str,
        query: str,
        value: Any,
        ttl: Optional[int] = None,
        filters: Optional[Dict] = None
    ) -> bool:
        """
        Cache result
        
        Args:
            source_name: Name of the source
            query: Search query
            value: Value to cache
            ttl: TTL in seconds (default: self.default_ttl)
            filters: Optional filters
        
        Returns:
            True if cached successfully
        """
        key = self._make_key(source_name, query, filters)
        ttl = ttl or self.default_ttl
        
        try:
            value_json = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize value for cache: {e}")
            return False
        
        if self._redis_client:
            try:
                self._redis_client.setex(key, ttl, value_json)
                return True
            except Exception as e:
                logger.warning(f"Error writing to Redis cache: {e}")
                return False
        else:
            # In-memory cache
            import time
            expiry = time.time() + ttl
            self._memory_cache[key] = (value, expiry)
            # Clean up expired entries periodically (simple approach: limit cache size)
            if len(self._memory_cache) > 1000:
                current_time = time.time()
                self._memory_cache = {
                    k: v for k, v in self._memory_cache.items()
                    if v[1] > current_time
                }
            return True
    
    def delete(self, source_name: str, query: str, filters: Optional[Dict] = None) -> bool:
        """
        Delete cached result
        
        Args:
            source_name: Name of the source
            query: Search query
            filters: Optional filters
        
        Returns:
            True if deleted successfully
        """
        key = self._make_key(source_name, query, filters)
        
        if self._redis_client:
            try:
                self._redis_client.delete(key)
                return True
            except Exception as e:
                logger.warning(f"Error deleting from Redis cache: {e}")
                return False
        else:
            # In-memory cache
            if key in self._memory_cache:
                del self._memory_cache[key]
                return True
        
        return False
    
    def clear(self, source_name: Optional[str] = None) -> bool:
        """
        Clear cache (optionally for a specific source)
        
        Args:
            source_name: Optional source name to clear (None = clear all)
        
        Returns:
            True if cleared successfully
        """
        if self._redis_client:
            try:
                if source_name:
                    pattern = f"external_source:{source_name}:*"
                    keys = self._redis_client.keys(pattern)
                    if keys:
                        self._redis_client.delete(*keys)
                else:
                    pattern = "external_source:*"
                    keys = self._redis_client.keys(pattern)
                    if keys:
                        self._redis_client.delete(*keys)
                return True
            except Exception as e:
                logger.warning(f"Error clearing Redis cache: {e}")
                return False
        else:
            # In-memory cache
            if source_name:
                prefix = f"external_source:{source_name}:"
                keys_to_delete = [k for k in self._memory_cache.keys() if k.startswith(prefix)]
                for key in keys_to_delete:
                    del self._memory_cache[key]
            else:
                self._memory_cache.clear()
            return True
    
    def health_check(self) -> bool:
        """Check if cache is healthy"""
        if self._redis_client:
            try:
                self._redis_client.ping()
                return True
            except Exception:
                return False
        return True  # In-memory cache is always available


# Global cache manager instance
_cache_manager: Optional[CacheManager] = None


def get_cache_manager(redis_url: Optional[str] = None, default_ttl: int = 3600) -> CacheManager:
    """
    Get or create global cache manager instance
    
    Args:
        redis_url: Redis connection URL
        default_ttl: Default TTL in seconds
    
    Returns:
        CacheManager instance
    """
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager(redis_url=redis_url, default_ttl=default_ttl)
    return _cache_manager

