"""Health checks for LangGraph system"""
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Статус здоровья компонента"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Информация о здоровье компонента"""
    name: str
    status: HealthStatus
    message: str
    details: Dict[str, Any] = None
    timestamp: str = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()
        if self.details is None:
            self.details = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp
        }


class HealthChecker:
    """Проверка здоровья системы"""
    
    def __init__(self):
        self.checks: List[Callable[[], ComponentHealth]] = []
        logger.info("HealthChecker initialized")
    
    def register_check(self, check_func: Callable[[], ComponentHealth]):
        """Зарегистрировать проверку здоровья"""
        self.checks.append(check_func)
        logger.debug(f"Registered health check: {check_func.__name__}")
    
    def check_all(self) -> Dict[str, ComponentHealth]:
        """
        Выполнить все проверки здоровья
        
        Returns:
            Словарь компонент -> ComponentHealth
        """
        results = {}
        
        for check_func in self.checks:
            try:
                health = check_func()
                results[health.name] = health
            except Exception as e:
                logger.error(f"Error in health check {check_func.__name__}: {e}", exc_info=True)
                results[check_func.__name__] = ComponentHealth(
                    name=check_func.__name__,
                    status=HealthStatus.UNKNOWN,
                    message=f"Error during check: {str(e)}"
                )
        
        return results
    
    def get_overall_status(self) -> HealthStatus:
        """Получить общий статус здоровья системы"""
        results = self.check_all()
        
        if not results:
            return HealthStatus.UNKNOWN
        
        statuses = [result.status for result in results.values()]
        
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        elif all(s == HealthStatus.HEALTHY for s in statuses):
            return HealthStatus.HEALTHY
        else:
            return HealthStatus.UNKNOWN
    
    def get_summary(self) -> Dict[str, Any]:
        """Получить сводку здоровья системы"""
        results = self.check_all()
        overall_status = self.get_overall_status()
        
        return {
            "overall_status": overall_status.value,
            "timestamp": datetime.now().isoformat(),
            "components": {
                name: health.to_dict()
                for name, health in results.items()
            }
        }


# Predefined health checks

def check_database_health() -> ComponentHealth:
    """Проверить здоровье базы данных"""
    try:
        from app.utils.database import get_db
        from sqlalchemy import text
        
        db = next(get_db())
        db.execute(text("SELECT 1"))
        
        return ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Database connection is healthy"
        )
    except Exception as e:
        return ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database connection failed: {str(e)}"
        )


def check_graph_health() -> ComponentHealth:
    """Проверить здоровье графа"""
    try:
        from app.services.langchain_agents.graph_monitoring import get_graph_monitor
        
        monitor = get_graph_monitor()
        summary = monitor.get_performance_summary()
        
        # Проверяем метрики
        if summary["total_errors"] > 100:
            return ComponentHealth(
                name="graph",
                status=HealthStatus.DEGRADED,
                message=f"High error rate: {summary['total_errors']} errors",
                details=summary
            )
        
        return ComponentHealth(
            name="graph",
            status=HealthStatus.HEALTHY,
            message="Graph system is healthy",
            details=summary
        )
    except Exception as e:
        return ComponentHealth(
            name="graph",
            status=HealthStatus.UNKNOWN,
            message=f"Error checking graph health: {str(e)}"
        )


def check_rag_service_health() -> ComponentHealth:
    """Проверить здоровье RAG сервиса"""
    try:
        from app.services.rag_service import RAGService
        
        # Простая проверка - можно улучшить
        return ComponentHealth(
            name="rag_service",
            status=HealthStatus.HEALTHY,
            message="RAG service is available"
        )
    except Exception as e:
        return ComponentHealth(
            name="rag_service",
            status=HealthStatus.UNHEALTHY,
            message=f"RAG service error: {str(e)}"
        )


# Global health checker instance
_global_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """Получить глобальный экземпляр health checker"""
    global _global_health_checker
    
    if _global_health_checker is None:
        _global_health_checker = HealthChecker()
        
        # Регистрируем стандартные проверки
        _global_health_checker.register_check(check_database_health)
        _global_health_checker.register_check(check_graph_health)
        _global_health_checker.register_check(check_rag_service_health)
    
    return _global_health_checker

