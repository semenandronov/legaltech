"""Presence Service for tracking user presence in tabular reviews"""
from typing import Dict, List, Set, Optional
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("Redis not available, using in-memory presence tracking")


class PresenceService:
    """Service for tracking user presence in tabular reviews"""
    
    def __init__(self, redis_url: Optional[str] = None):
        """Initialize presence service"""
        self.redis_available = REDIS_AVAILABLE
        self.in_memory_store: Dict[str, Dict[str, datetime]] = {}  # {review_id: {user_id: last_seen}}
        
        if self.redis_available and redis_url:
            try:
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_available = True
                logger.info("Redis presence service initialized")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis: {e}, using in-memory storage")
                self.redis_available = False
        else:
            self.redis_available = False
            logger.info("Using in-memory presence tracking (Redis not configured)")
    
    def _get_key(self, review_id: str) -> str:
        """Get Redis key for review presence"""
        return f"presence:tabular_review:{review_id}"
    
    def _get_user_key(self, review_id: str, user_id: str) -> str:
        """Get Redis key for user presence in review"""
        return f"presence:tabular_review:{review_id}:user:{user_id}"
    
    def update_presence(self, review_id: str, user_id: str, user_name: Optional[str] = None) -> None:
        """Update user presence in a review"""
        now = datetime.utcnow()
        presence_data = {
            "user_id": user_id,
            "user_name": user_name or user_id,
            "last_seen": now.isoformat(),
        }
        
        if self.redis_available:
            try:
                key = self._get_user_key(review_id, user_id)
                review_key = self._get_key(review_id)
                
                # Set user presence with 60 second TTL
                self.redis_client.setex(
                    key,
                    60,  # TTL in seconds
                    json.dumps(presence_data)
                )
                
                # Add user to review set
                self.redis_client.sadd(review_key, user_id)
                self.redis_client.expire(review_key, 60)
                
                logger.debug(f"Updated presence for user {user_id} in review {review_id}")
            except Exception as e:
                logger.error(f"Error updating presence in Redis: {e}", exc_info=True)
        else:
            # In-memory storage
            if review_id not in self.in_memory_store:
                self.in_memory_store[review_id] = {}
            self.in_memory_store[review_id][user_id] = now
            
            # Cleanup old entries (older than 60 seconds)
            cutoff = now - timedelta(seconds=60)
            self.in_memory_store[review_id] = {
                uid: last_seen
                for uid, last_seen in self.in_memory_store[review_id].items()
                if last_seen > cutoff
            }
    
    def get_present_users(self, review_id: str) -> List[Dict[str, any]]:
        """Get list of users currently present in a review"""
        if self.redis_available:
            try:
                review_key = self._get_key(review_id)
                user_ids = self.redis_client.smembers(review_key)
                
                present_users = []
                for user_id in user_ids:
                    user_key = self._get_user_key(review_id, user_id)
                    user_data_str = self.redis_client.get(user_key)
                    
                    if user_data_str:
                        try:
                            user_data = json.loads(user_data_str)
                            # Check if still valid (within 60 seconds)
                            last_seen = datetime.fromisoformat(user_data["last_seen"])
                            if datetime.utcnow() - last_seen < timedelta(seconds=60):
                                present_users.append(user_data)
                        except (json.JSONDecodeError, KeyError, ValueError) as e:
                            logger.warning(f"Error parsing user presence data: {e}")
                            continue
                
                return present_users
            except Exception as e:
                logger.error(f"Error getting presence from Redis: {e}", exc_info=True)
                return []
        else:
            # In-memory storage
            if review_id not in self.in_memory_store:
                return []
            
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=60)
            
            present_users = []
            for user_id, last_seen in self.in_memory_store[review_id].items():
                if last_seen > cutoff:
                    present_users.append({
                        "user_id": user_id,
                        "user_name": user_id,  # In-memory doesn't store names
                        "last_seen": last_seen.isoformat(),
                    })
            
            return present_users
    
    def remove_presence(self, review_id: str, user_id: str) -> None:
        """Remove user presence from a review"""
        if self.redis_available:
            try:
                key = self._get_user_key(review_id, user_id)
                review_key = self._get_key(review_id)
                
                self.redis_client.delete(key)
                self.redis_client.srem(review_key, user_id)
                
                logger.debug(f"Removed presence for user {user_id} in review {review_id}")
            except Exception as e:
                logger.error(f"Error removing presence from Redis: {e}", exc_info=True)
        else:
            # In-memory storage
            if review_id in self.in_memory_store:
                self.in_memory_store[review_id].pop(user_id, None)
    
    def is_user_present(self, review_id: str, user_id: str) -> bool:
        """Check if user is currently present in review"""
        present_users = self.get_present_users(review_id)
        return any(user["user_id"] == user_id for user in present_users)
    
    def get_review_presence_count(self, review_id: str) -> int:
        """Get count of users currently present in review"""
        return len(self.get_present_users(review_id))
    
    def cleanup_old_presence(self) -> None:
        """Clean up old presence entries (for in-memory storage)"""
        if not self.redis_available:
            now = datetime.utcnow()
            cutoff = now - timedelta(seconds=60)
            
            for review_id in list(self.in_memory_store.keys()):
                self.in_memory_store[review_id] = {
                    uid: last_seen
                    for uid, last_seen in self.in_memory_store[review_id].items()
                    if last_seen > cutoff
                }
                
                # Remove empty reviews
                if not self.in_memory_store[review_id]:
                    del self.in_memory_store[review_id]


# Create global instance (will be initialized with config in routes)
presence_service_instance: Optional[PresenceService] = None


def get_presence_service(redis_url: Optional[str] = None) -> PresenceService:
    """Get or create global presence service instance"""
    global presence_service_instance
    if presence_service_instance is None:
        presence_service_instance = PresenceService(redis_url=redis_url)
    return presence_service_instance

