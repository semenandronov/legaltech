"""Rate limiter for external API calls"""
from typing import Optional, Dict
import time
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Rate limiter for external API calls.
    
    Implements token bucket algorithm for rate limiting.
    """
    
    def __init__(
        self,
        requests_per_second: float = 10.0,
        burst_size: Optional[int] = None
    ):
        """
        Initialize rate limiter
        
        Args:
            requests_per_second: Maximum requests per second (default: 10)
            burst_size: Maximum burst size (default: requests_per_second * 2)
        """
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size or int(requests_per_second * 2)
        self.tokens = self.burst_size
        self.last_update = time.time()
        self._lock = asyncio.Lock()
        
        # Per-source rate limiters
        self._source_limiters: Dict[str, 'RateLimiter'] = {}
    
    async def acquire(self, source_name: Optional[str] = None) -> bool:
        """
        Acquire permission to make a request (non-blocking)
        
        Args:
            source_name: Optional source name for per-source limiting
        
        Returns:
            True if request is allowed, False if rate limited
        """
        limiter = self._get_limiter(source_name)
        
        async with limiter._lock:
            now = time.time()
            elapsed = now - limiter.last_update
            
            # Refill tokens based on elapsed time
            tokens_to_add = elapsed * limiter.requests_per_second
            limiter.tokens = min(limiter.burst_size, limiter.tokens + tokens_to_add)
            limiter.last_update = now
            
            if limiter.tokens >= 1.0:
                limiter.tokens -= 1.0
                return True
            else:
                logger.debug(f"Rate limit exceeded for {source_name or 'default'}")
                return False
    
    async def wait(self, source_name: Optional[str] = None) -> None:
        """
        Wait until a request can be made (blocking)
        
        Args:
            source_name: Optional source name for per-source limiting
        """
        limiter = self._get_limiter(source_name)
        
        while not await limiter.acquire(source_name):
            # Calculate wait time
            tokens_needed = 1.0 - limiter.tokens
            wait_time = tokens_needed / limiter.requests_per_second
            wait_time = max(0.1, min(wait_time, 1.0))  # Cap at 1 second
            
            await asyncio.sleep(wait_time)
    
    def _get_limiter(self, source_name: Optional[str] = None) -> 'RateLimiter':
        """Get limiter for source (or default)"""
        if source_name is None:
            return self
        
        if source_name not in self._source_limiters:
            # Create per-source limiter with same settings
            self._source_limiters[source_name] = RateLimiter(
                requests_per_second=self.requests_per_second,
                burst_size=self.burst_size
            )
        
        return self._source_limiters[source_name]
    
    def reset(self, source_name: Optional[str] = None) -> None:
        """
        Reset rate limiter
        
        Args:
            source_name: Optional source name to reset
        """
        if source_name is None:
            self.tokens = self.burst_size
            self.last_update = time.time()
        elif source_name in self._source_limiters:
            self._source_limiters[source_name].reset()


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter(
    requests_per_second: float = 10.0,
    burst_size: Optional[int] = None
) -> RateLimiter:
    """
    Get or create global rate limiter instance
    
    Args:
        requests_per_second: Maximum requests per second
        burst_size: Maximum burst size
    
    Returns:
        RateLimiter instance
    """
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(
            requests_per_second=requests_per_second,
            burst_size=burst_size
        )
    return _rate_limiter


# Per-source rate limit configurations
SOURCE_RATE_LIMITS = {
    "pravo_gov": {"requests_per_second": 5.0, "burst_size": 10},
    "vsrf": {"requests_per_second": 5.0, "burst_size": 10},
    "kad_arbitr": {"requests_per_second": 5.0, "burst_size": 10},
    "web_search": {"requests_per_second": 2.0, "burst_size": 5},  # Yandex API limits
    "default": {"requests_per_second": 10.0, "burst_size": 20},
}


def get_source_rate_limiter(source_name: str) -> RateLimiter:
    """
    Get rate limiter for a specific source
    
    Args:
        source_name: Name of the source
    
    Returns:
        RateLimiter instance configured for the source
    """
    config = SOURCE_RATE_LIMITS.get(source_name, SOURCE_RATE_LIMITS["default"])
    return RateLimiter(
        requests_per_second=config["requests_per_second"],
        burst_size=config["burst_size"]
    )

