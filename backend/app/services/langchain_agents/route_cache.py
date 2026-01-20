"""Route Cache for caching supervisor routing decisions"""
from typing import Optional, Dict, Any
from app.services.langchain_agents.state import AnalysisState
import hashlib
import json
import time
import logging

logger = logging.getLogger(__name__)

# TTL для кэша (1 час)
CACHE_TTL_SECONDS = 3600


class RouteCache:
    """
    Кэш для решений supervisor маршрутизации
    
    Кэширует решения на основе fingerprint состояния:
    - analysis_types
    - completed_steps
    - Результаты агентов (только наличие, не содержимое)
    
    TTL: 1 час
    Инвалидация при изменении analysis_types или completed_steps
    """
    
    def __init__(self, ttl_seconds: int = CACHE_TTL_SECONDS):
        """
        Инициализация RouteCache
        
        Args:
            ttl_seconds: Время жизни кэша в секундах
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds
        self.max_size = 1000  # Максимум записей в кэше
    
    def _create_fingerprint(self, state: AnalysisState) -> str:
        """
        Создать fingerprint состояния для кэш-ключа
        
        Args:
            state: Состояние анализа
        
        Returns:
            Хеш-строка fingerprint
        """
        # Извлекаем ключевые поля для fingerprint
        fingerprint_data = {
            "analysis_types": sorted(state.get("analysis_types", [])),
            "completed_steps": sorted(state.get("completed_steps", [])),
            # Результаты агентов (только наличие)
            "results": {
                "timeline": state.get("timeline_result") is not None or state.get("timeline_ref") is not None,
                "key_facts": state.get("key_facts_result") is not None or state.get("key_facts_ref") is not None,
                "discrepancy": state.get("discrepancy_result") is not None or state.get("discrepancy_ref") is not None,
                "risk": state.get("risk_result") is not None or state.get("risk_ref") is not None,
                "summary": state.get("summary_result") is not None or state.get("summary_ref") is not None,
                "classification": state.get("classification_result") is not None or state.get("classification_ref") is not None,
                "entities": state.get("entities_result") is not None or state.get("entities_ref") is not None,
                "privilege": state.get("privilege_result") is not None or state.get("privilege_ref") is not None,
                "relationship": state.get("relationship_result") is not None or state.get("relationship_ref") is not None,
            }
        }
        
        # Создать хеш
        fingerprint_str = json.dumps(fingerprint_data, sort_keys=True)
        fingerprint_hash = hashlib.md5(fingerprint_str.encode()).hexdigest()
        
        return fingerprint_hash
    
    def get(self, state: AnalysisState) -> Optional[str]:
        """
        Получить закэшированное решение
        
        Args:
            state: Состояние анализа
        
        Returns:
            Имя агента или None если не найдено/истекло
        """
        fingerprint = self._create_fingerprint(state)
        
        if fingerprint not in self.cache:
            return None
        
        cache_entry = self.cache[fingerprint]
        
        # Проверить TTL
        if time.time() - cache_entry["timestamp"] > self.ttl:
            # Удалить устаревшую запись
            del self.cache[fingerprint]
            logger.debug(f"[RouteCache] Cache entry expired: {fingerprint[:8]}")
            return None
        
        route = cache_entry["route"]
        logger.debug(f"[RouteCache] Cache hit: {fingerprint[:8]} → {route}")
        return route
    
    def set(self, state: AnalysisState, route: str) -> None:
        """
        Сохранить решение в кэш
        
        Args:
            state: Состояние анализа
            route: Имя агента
        """
        fingerprint = self._create_fingerprint(state)
        
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
            logger.debug(f"[RouteCache] Evicted oldest entry: {oldest_fingerprint[:8]}")
        
        # Сохранить новую запись
        self.cache[fingerprint] = {
            "route": route,
            "timestamp": time.time()
        }
        
        logger.debug(f"[RouteCache] Cached route: {fingerprint[:8]} → {route}")
    
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
            logger.debug(f"[RouteCache] Cleaned up {len(expired_keys)} expired entries")
    
    def clear(self) -> None:
        """Очистить весь кэш"""
        self.cache.clear()
        logger.info("[RouteCache] Cache cleared")
    
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
_route_cache = None


def get_route_cache() -> RouteCache:
    """Получить глобальный экземпляр RouteCache"""
    global _route_cache
    if _route_cache is None:
        _route_cache = RouteCache()
    return _route_cache









































