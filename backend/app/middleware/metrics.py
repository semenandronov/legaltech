"""Metrics and monitoring middleware"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

# Simple in-memory metrics storage (can be replaced with Prometheus/StatsD in production)
_metrics_store = {
    "request_count": 0,
    "request_durations": [],
    "error_count": 0,
    "llm_calls": 0,
    "agent_executions": {},
    "last_reset": datetime.utcnow()
}


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware for tracking request metrics"""
    
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


def track_llm_call(model: str, duration: float, tokens: int = None):
    """Track LLM API call"""
    _metrics_store["llm_calls"] += 1
    logger.debug(f"LLM call: {model}, duration: {duration:.2f}s, tokens: {tokens}")


def track_agent_execution(agent_name: str, duration: float, success: bool = True):
    """Track agent execution time"""
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
    """Get current metrics"""
    durations = _metrics_store["request_durations"]
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    p95_duration = sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 20 else 0.0
    
    # Calculate agent stats
    agent_stats = {}
    for agent_name, stats in _metrics_store["agent_executions"].items():
        avg_agent_duration = stats["total_duration"] / stats["count"] if stats["count"] > 0 else 0.0
        agent_stats[agent_name] = {
            "count": stats["count"],
            "avg_duration": avg_agent_duration,
            "success_rate": stats["success_count"] / stats["count"] if stats["count"] > 0 else 0.0
        }
    
    return {
        "request_count": _metrics_store["request_count"],
        "error_count": _metrics_store["error_count"],
        "avg_request_duration": avg_duration,
        "p95_request_duration": p95_duration,
        "llm_calls": _metrics_store["llm_calls"],
        "agent_executions": agent_stats,
        "uptime_seconds": (datetime.utcnow() - _metrics_store["last_reset"]).total_seconds()
    }


def reset_metrics():
    """Reset metrics (for testing or periodic reset)"""
    global _metrics_store
    _metrics_store = {
        "request_count": 0,
        "request_durations": [],
        "error_count": 0,
        "llm_calls": 0,
        "agent_executions": {},
        "last_reset": datetime.utcnow()
    }

