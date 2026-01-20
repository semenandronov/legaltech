"""
Health Endpoints - Эндпоинты проверки здоровья

Предоставляет:
- /api/health - базовая проверка
- /api/health/live - liveness probe
- /api/health/ready - readiness probe
- /api/health/detailed - детальная проверка всех компонентов
"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from typing import Optional

from app.core.health import get_health_checker, HealthStatus

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health():
    """
    Базовая проверка здоровья
    
    Возвращает статус сервиса.
    """
    checker = get_health_checker()
    return {
        "status": "ok",
        "uptime_seconds": round(checker.uptime, 2)
    }


@router.get("/api/health/live")
async def liveness():
    """
    Liveness probe для Kubernetes
    
    Проверяет что сервис запущен и отвечает.
    """
    checker = get_health_checker()
    result = await checker.liveness()
    return result


@router.get("/api/health/ready")
async def readiness():
    """
    Readiness probe для Kubernetes
    
    Проверяет что сервис готов принимать запросы.
    Проверяет критичные зависимости (БД).
    """
    checker = get_health_checker()
    result = await checker.readiness()
    
    if result["status"] != "ready":
        return JSONResponse(
            status_code=503,
            content=result
        )
    
    return result


@router.get("/api/health/detailed")
async def detailed_health(include_optional: bool = True):
    """
    Детальная проверка здоровья всех компонентов
    
    Args:
        include_optional: Включать опциональные проверки (LLM, ГАРАНТ)
    
    Проверяет:
    - База данных
    - Redis
    - RAG сервис
    - LLM (опционально)
    - ГАРАНТ API (опционально)
    """
    checker = get_health_checker()
    report = await checker.check_all(include_optional=include_optional)
    
    status_code = 200
    if report.status == HealthStatus.UNHEALTHY:
        status_code = 503
    elif report.status == HealthStatus.DEGRADED:
        status_code = 200  # Degraded всё ещё работает
    
    return JSONResponse(
        status_code=status_code,
        content=report.to_dict()
    )


@router.get("/api/metrics/chat")
async def chat_metrics():
    """
    Метрики чата
    
    Возвращает статистику по запросам, латентности, ошибкам.
    """
    from app.services.chat.metrics import get_metrics
    
    metrics = get_metrics()
    return metrics.get_summary()


@router.get("/api/metrics/circuit-breakers")
async def circuit_breaker_status():
    """
    Статус Circuit Breaker'ов
    
    Возвращает состояние всех Circuit Breaker'ов в системе.
    """
    from app.core.resilience import CircuitBreakerRegistry
    
    return CircuitBreakerRegistry.get_status()


@router.get("/api/metrics/rate-limits")
async def rate_limit_status():
    """
    Статус Rate Limiter
    
    Возвращает текущее состояние rate limiting.
    """
    from app.core.rate_limiter import get_rate_limiter
    
    limiter = get_rate_limiter()
    return limiter.get_status()

