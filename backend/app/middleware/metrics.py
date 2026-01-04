"""Metrics and monitoring middleware - Phase 4.2 Enhanced

Provides request tracking, LLM call metrics, and Prometheus integration.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import Prometheus metrics
try:
    from app.services.metrics.prometheus_exporter import (
        get_metrics_collector,
        PROMETHEUS_AVAILABLE
    )
    HAS_PROMETHEUS = PROMETHEUS_AVAILABLE
except ImportError:
    HAS_PROMETHEUS = False
    get_metrics_collector = None

# Try to import rate limiter stats
try:
    from app.services.rate_limiter import get_rate_limit_stats
    HAS_RATE_LIMITER = True
except ImportError:
    HAS_RATE_LIMITER = False
    get_rate_limit_stats = None

# Simple in-memory metrics storage
_metrics_store = {
    "request_count": 0,
    "request_durations": [],
    "error_count": 0,
    "llm_calls": 0,
    "llm_total_duration": 0.0,
    "llm_total_tokens": 0,
    "agent_executions": {},
    "last_reset": datetime.utcnow()
}


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking request metrics with Prometheus integration."""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Track request
        _metrics_store["request_count"] += 1
        
        try:
            response = await call_next(request)
            process_time = time.time() - start_time
            
            # Track duration (keep last 1000 requests)
            _metrics_store["request_durations"].append(process_time)
            if len(_metrics_store["request_durations"]) > 1000:
                _metrics_store["request_durations"] = _metrics_store["request_durations"][-1000:]
            
            # Add timing header
            response.headers["X-Process-Time"] = str(process_time)
            
            # Log slow requests
            if process_time > 5.0:
                logger.warning(f"Slow request: {request.method} {request.url.path} took {process_time:.2f}s")
            
            return response
        except Exception as e:
            _metrics_store["error_count"] += 1
            logger.error(f"Request error: {request.method} {request.url.path}: {e}", exc_info=True)
            raise


def track_llm_call(
    model: str,
    duration: float,
    tokens: Optional[int] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    agent_type: str = "unknown",
    success: bool = True
):
    """Track LLM API call with enhanced metrics."""
    _metrics_store["llm_calls"] += 1
    _metrics_store["llm_total_duration"] += duration
    
    total_tokens = tokens or (input_tokens or 0) + (output_tokens or 0)
    _metrics_store["llm_total_tokens"] += total_tokens
    
    logger.debug(f"LLM call: {model}, duration: {duration:.2f}s, tokens: {total_tokens}")

    # Record to Prometheus if available
    if HAS_PROMETHEUS and get_metrics_collector:
        collector = get_metrics_collector()
        collector.record_tokens_used(
            input_tokens=input_tokens or 0,
            output_tokens=output_tokens or 0,
            model=model,
            agent_type=agent_type
        )


def track_agent_execution(
    agent_name: str,
    duration: float,
    success: bool = True,
    case_id: str = "unknown"
):
    """Track agent execution time with enhanced metrics."""
    if agent_name not in _metrics_store["agent_executions"]:
        _metrics_store["agent_executions"][agent_name] = {
            "count": 0,
            "total_duration": 0.0,
            "success_count": 0,
            "error_count": 0
        }
    
    stats = _metrics_store["agent_executions"][agent_name]
    stats["count"] += 1
    stats["total_duration"] += duration
    
    if success:
        stats["success_count"] += 1
    else:
        stats["error_count"] += 1
    
    logger.debug(f"Agent {agent_name}: {duration:.2f}s, success: {success}")


def get_metrics() -> Dict[str, Any]:
    """Get current metrics including Prometheus and rate limiter stats."""
    durations = _metrics_store["request_durations"]
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    p95_duration = sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else 0.0
    
    # Calculate agent stats
    agent_stats = {}
    for agent_name, stats in _metrics_store["agent_executions"].items():
        avg_agent_duration = stats["total_duration"] / stats["count"] if stats["count"] > 0 else 0.0
        agent_stats[agent_name] = {
            "count": stats["count"],
            "avg_duration": round(avg_agent_duration, 3),
            "success_rate": round(stats["success_count"] / stats["count"], 3) if stats["count"] > 0 else 0.0
        }
    
    # LLM stats
    llm_avg_duration = 0.0
    if _metrics_store["llm_calls"] > 0:
        llm_avg_duration = _metrics_store["llm_total_duration"] / _metrics_store["llm_calls"]
    
    result = {
        "request_count": _metrics_store["request_count"],
        "error_count": _metrics_store["error_count"],
        "avg_request_duration": round(avg_duration, 3),
        "p95_request_duration": round(p95_duration, 3),
        "llm_calls": _metrics_store["llm_calls"],
        "llm_avg_duration": round(llm_avg_duration, 3),
        "llm_total_tokens": _metrics_store["llm_total_tokens"],
        "agent_executions": agent_stats,
        "uptime_seconds": (datetime.utcnow() - _metrics_store["last_reset"]).total_seconds()
    }
    
    # Add rate limiter stats if available
    if HAS_RATE_LIMITER and get_rate_limit_stats:
        try:
            result["rate_limiting"] = get_rate_limit_stats()
        except Exception as e:
            logger.debug(f"Could not get rate limiter stats: {e}")
    
    # Add Prometheus metrics summary if available
    if HAS_PROMETHEUS and get_metrics_collector:
        try:
            collector = get_metrics_collector()
            result["prometheus"] = collector.get_summary()
        except Exception as e:
            logger.debug(f"Could not get Prometheus stats: {e}")
    
    return result


def get_prometheus_metrics() -> tuple:
    """
    Get Prometheus-formatted metrics output.
    
    Returns:
        Tuple of (content_bytes, content_type)
    """
    if HAS_PROMETHEUS and get_metrics_collector:
        collector = get_metrics_collector()
        return collector.get_metrics_output(), collector.get_content_type()
    return b"# Prometheus metrics not available\n", "text/plain"


def reset_metrics():
    """Reset metrics (for testing or periodic reset)."""
    global _metrics_store
    _metrics_store = {
        "request_count": 0,
        "request_durations": [],
        "error_count": 0,
        "llm_calls": 0,
        "llm_total_duration": 0.0,
        "llm_total_tokens": 0,
        "agent_executions": {},
        "last_reset": datetime.utcnow()
    }




