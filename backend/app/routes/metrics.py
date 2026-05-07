"""System Metrics Routes - Phase 4.2 Implementation

Provides endpoints for:
- Application metrics (JSON format)
- Prometheus metrics (Prometheus format)
- Rate limiter status
- Health check with metrics
"""
from fastapi import APIRouter, Response, Depends, HTTPException
from typing import Dict, Any
from pydantic import BaseModel, Field
from app.middleware.metrics import get_metrics, get_prometheus_metrics
from app.utils.auth import get_current_user
from app.models.user import User
from app.services.observability.langfuse_service import record_score
from app.services.chat.metrics import get_metrics as get_chat_metrics
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class AssistantFeedbackRequest(BaseModel):
    trace_id: str = Field(..., description="Langfuse trace id")
    rating: str = Field(..., description="positive|negative")
    reason: str | None = Field(default=None, description="Код причины")
    comment: str | None = Field(default=None, description="Свободный комментарий")


@router.get("/")
async def get_application_metrics(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get application metrics in JSON format.
    
    Includes:
    - Request statistics
    - LLM call metrics
    - Agent execution metrics
    - Rate limiting stats (if enabled)
    - Prometheus summary (if available)
    
    Requires authentication.
    """
    return get_metrics()


@router.get("/prometheus")
async def get_prometheus_metrics_endpoint() -> Response:
    """
    Get metrics in Prometheus format.
    
    This endpoint is typically used by Prometheus scraper.
    Returns metrics in Prometheus exposition format.
    
    Note: This endpoint does not require authentication
    to allow Prometheus to scrape metrics.
    """
    content, content_type = get_prometheus_metrics()
    return Response(content=content, media_type=content_type)


@router.get("/rate-limit")
async def get_rate_limit_status(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get current rate limiting status.
    
    Returns:
    - Rate limit configuration
    - Available tokens
    - Current concurrent LLM calls
    - Available slots
    
    Requires authentication.
    """
    try:
        from app.services.rate_limiter import get_rate_limit_stats
        return get_rate_limit_stats()
    except ImportError:
        return {
            "error": "Rate limiter not available",
            "rate_limit_enabled": False
        }


@router.get("/health")
async def health_check_with_metrics() -> Dict[str, Any]:
    """
    Health check endpoint with basic metrics.
    
    Returns:
    - Service status
    - Uptime
    - Basic request counts
    
    Does not require authentication.
    """
    metrics = get_metrics()
    
    return {
        "status": "healthy",
        "uptime_seconds": metrics.get("uptime_seconds", 0),
        "request_count": metrics.get("request_count", 0),
        "error_count": metrics.get("error_count", 0),
        "llm_calls": metrics.get("llm_calls", 0),
        "rate_limiting": metrics.get("rate_limiting", {})
    }


@router.get("/llm")
async def get_llm_metrics(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get LLM-specific metrics.
    
    Returns:
    - Total LLM calls
    - Average latency
    - Token usage
    - Error rates
    
    Requires authentication.
    """
    metrics = get_metrics()
    
    return {
        "llm_calls": metrics.get("llm_calls", 0),
        "llm_avg_duration": metrics.get("llm_avg_duration", 0),
        "llm_total_tokens": metrics.get("llm_total_tokens", 0),
        "rate_limiting": metrics.get("rate_limiting", {}),
        "prometheus": metrics.get("prometheus", {})
    }


@router.get("/agents")
async def get_agent_metrics(
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get agent execution metrics.
    
    Returns per-agent statistics:
    - Execution count
    - Average duration
    - Success rate
    
    Requires authentication.
    """
    metrics = get_metrics()
    
    return {
        "agent_executions": metrics.get("agent_executions", {}),
        "prometheus": metrics.get("prometheus", {})
    }


@router.post("/assistant-feedback")
async def submit_assistant_feedback(
    payload: AssistantFeedbackRequest,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Сохранить feedback по ответу ассистента и отправить score в Langfuse.
    """
    rating = (payload.rating or "").strip().lower()
    if rating not in {"positive", "negative"}:
        raise HTTPException(status_code=400, detail="rating must be 'positive' or 'negative'")

    score_value = 1.0 if rating == "positive" else 0.0
    score_name = "assistant_user_feedback"
    metadata = {
        "user_id": str(current_user.id),
        "reason": payload.reason,
        "rating": rating,
    }
    score_sent = record_score(
        trace_id=payload.trace_id.strip(),
        name=score_name,
        value=score_value,
        comment=payload.comment,
        metadata=metadata,
    )
    get_chat_metrics().record_feedback(rating)
    return {"ok": True, "score_sent": score_sent}

