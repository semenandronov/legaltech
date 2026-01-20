"""
Health Checks - Проверка состояния сервисов

Предоставляет:
- Liveness probe (сервис запущен)
- Readiness probe (сервис готов принимать запросы)
- Детальные health checks для каждого компонента
"""
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Статус здоровья"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Здоровье компонента"""
    name: str
    status: HealthStatus
    message: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "details": self.details,
            "checked_at": self.checked_at.isoformat()
        }


@dataclass
class HealthReport:
    """Отчёт о здоровье системы"""
    status: HealthStatus
    components: List[ComponentHealth]
    version: str = "1.0.0"
    uptime_seconds: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "components": [c.to_dict() for c in self.components],
            "timestamp": datetime.utcnow().isoformat()
        }


class HealthChecker:
    """
    Сервис проверки здоровья системы
    
    Проверяет:
    - База данных
    - Redis (кэш)
    - LLM сервис
    - RAG сервис
    - Внешние API (ГАРАНТ)
    """
    
    _start_time: float = None
    
    def __init__(self):
        if HealthChecker._start_time is None:
            HealthChecker._start_time = time.time()
    
    @property
    def uptime(self) -> float:
        """Время работы в секундах"""
        if self._start_time:
            return time.time() - self._start_time
        return 0
    
    async def check_database(self) -> ComponentHealth:
        """Проверить подключение к БД"""
        start = time.time()
        try:
            from app.utils.database import get_db
            from sqlalchemy import text
            
            db = next(get_db())
            result = db.execute(text("SELECT 1"))
            result.fetchone()
            db.close()
            
            latency = (time.time() - start) * 1000
            
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                message="PostgreSQL connection OK",
                latency_ms=round(latency, 2)
            )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.error(f"Database health check failed: {e}")
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Connection failed: {str(e)[:100]}",
                latency_ms=round(latency, 2)
            )
    
    async def check_redis(self) -> ComponentHealth:
        """Проверить подключение к Redis"""
        start = time.time()
        try:
            from app.services.external_sources.cache_manager import get_cache_manager
            
            cache = get_cache_manager()
            
            # Пробуем записать и прочитать
            test_key = "_health_check_"
            cache.set("health", test_key, {"test": True}, ttl=10)
            result = cache.get("health", test_key)
            
            latency = (time.time() - start) * 1000
            
            if result:
                return ComponentHealth(
                    name="redis",
                    status=HealthStatus.HEALTHY,
                    message="Redis connection OK",
                    latency_ms=round(latency, 2)
                )
            else:
                return ComponentHealth(
                    name="redis",
                    status=HealthStatus.DEGRADED,
                    message="Redis connected but read failed",
                    latency_ms=round(latency, 2)
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"Redis health check failed: {e}")
            return ComponentHealth(
                name="redis",
                status=HealthStatus.DEGRADED,  # Redis не критичен
                message=f"Connection failed: {str(e)[:100]}",
                latency_ms=round(latency, 2)
            )
    
    async def check_llm(self) -> ComponentHealth:
        """Проверить LLM сервис"""
        start = time.time()
        try:
            from app.services.llm_factory import create_llm
            from langchain_core.messages import HumanMessage
            
            llm = create_llm(temperature=0, max_tokens=10)
            response = llm.invoke([HumanMessage(content="Ответь: OK")])
            
            latency = (time.time() - start) * 1000
            
            if response and hasattr(response, 'content'):
                return ComponentHealth(
                    name="llm",
                    status=HealthStatus.HEALTHY,
                    message="LLM service OK",
                    latency_ms=round(latency, 2),
                    details={"model": "GigaChat"}
                )
            else:
                return ComponentHealth(
                    name="llm",
                    status=HealthStatus.DEGRADED,
                    message="LLM responded but with unexpected format",
                    latency_ms=round(latency, 2)
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.error(f"LLM health check failed: {e}")
            return ComponentHealth(
                name="llm",
                status=HealthStatus.UNHEALTHY,
                message=f"LLM error: {str(e)[:100]}",
                latency_ms=round(latency, 2)
            )
    
    async def check_rag(self) -> ComponentHealth:
        """Проверить RAG сервис"""
        start = time.time()
        try:
            from app.services.rag_service import RAGService
            
            rag = RAGService()
            
            # Проверяем что embeddings работают
            # (без реального запроса к БД)
            if rag.embeddings:
                latency = (time.time() - start) * 1000
                return ComponentHealth(
                    name="rag",
                    status=HealthStatus.HEALTHY,
                    message="RAG service initialized",
                    latency_ms=round(latency, 2)
                )
            else:
                return ComponentHealth(
                    name="rag",
                    status=HealthStatus.DEGRADED,
                    message="RAG service initialized but embeddings not available",
                    latency_ms=round((time.time() - start) * 1000, 2)
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.error(f"RAG health check failed: {e}")
            return ComponentHealth(
                name="rag",
                status=HealthStatus.UNHEALTHY,
                message=f"RAG error: {str(e)[:100]}",
                latency_ms=round(latency, 2)
            )
    
    async def check_garant(self) -> ComponentHealth:
        """Проверить ГАРАНТ API"""
        start = time.time()
        try:
            from app.services.langchain_agents.garant_tools import get_garant_source
            
            garant = get_garant_source()
            
            if garant and garant.api_key:
                latency = (time.time() - start) * 1000
                return ComponentHealth(
                    name="garant",
                    status=HealthStatus.HEALTHY,
                    message="ГАРАНТ API configured",
                    latency_ms=round(latency, 2)
                )
            else:
                return ComponentHealth(
                    name="garant",
                    status=HealthStatus.DEGRADED,
                    message="ГАРАНТ API not configured",
                    latency_ms=round((time.time() - start) * 1000, 2)
                )
        except Exception as e:
            latency = (time.time() - start) * 1000
            logger.warning(f"ГАРАНТ health check failed: {e}")
            return ComponentHealth(
                name="garant",
                status=HealthStatus.DEGRADED,  # ГАРАНТ не критичен
                message=f"ГАРАНТ error: {str(e)[:100]}",
                latency_ms=round(latency, 2)
            )
    
    async def check_all(self, include_optional: bool = True) -> HealthReport:
        """
        Проверить все компоненты
        
        Args:
            include_optional: Включать опциональные проверки (LLM, ГАРАНТ)
        """
        # Критичные проверки
        critical_checks = [
            self.check_database(),
        ]
        
        # Важные проверки
        important_checks = [
            self.check_redis(),
            self.check_rag(),
        ]
        
        # Опциональные проверки
        optional_checks = []
        if include_optional:
            optional_checks = [
                self.check_llm(),
                self.check_garant(),
            ]
        
        # Выполняем все проверки параллельно
        all_checks = critical_checks + important_checks + optional_checks
        results = await asyncio.gather(*all_checks, return_exceptions=True)
        
        components = []
        for result in results:
            if isinstance(result, Exception):
                components.append(ComponentHealth(
                    name="unknown",
                    status=HealthStatus.UNHEALTHY,
                    message=str(result)
                ))
            else:
                components.append(result)
        
        # Определяем общий статус
        overall_status = self._calculate_overall_status(components)
        
        return HealthReport(
            status=overall_status,
            components=components,
            uptime_seconds=round(self.uptime, 2)
        )
    
    def _calculate_overall_status(self, components: List[ComponentHealth]) -> HealthStatus:
        """Вычислить общий статус"""
        critical_components = {"database"}
        
        for component in components:
            if component.name in critical_components:
                if component.status == HealthStatus.UNHEALTHY:
                    return HealthStatus.UNHEALTHY
        
        # Проверяем есть ли degraded
        has_degraded = any(c.status == HealthStatus.DEGRADED for c in components)
        has_unhealthy = any(
            c.status == HealthStatus.UNHEALTHY and c.name not in critical_components
            for c in components
        )
        
        if has_unhealthy:
            return HealthStatus.DEGRADED
        if has_degraded:
            return HealthStatus.DEGRADED
        
        return HealthStatus.HEALTHY
    
    async def liveness(self) -> Dict[str, Any]:
        """
        Liveness probe - сервис запущен
        
        Минимальная проверка для Kubernetes liveness probe.
        """
        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    async def readiness(self) -> Dict[str, Any]:
        """
        Readiness probe - сервис готов принимать запросы
        
        Проверяет критичные зависимости.
        """
        db_health = await self.check_database()
        
        if db_health.status == HealthStatus.UNHEALTHY:
            return {
                "status": "not_ready",
                "reason": "database_unavailable",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        return {
            "status": "ready",
            "timestamp": datetime.utcnow().isoformat()
        }


# =============================================================================
# Global Health Checker Instance
# =============================================================================

_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Получить глобальный health checker"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker

