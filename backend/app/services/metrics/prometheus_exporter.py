"""Prometheus Metrics Exporter - Phase 4.2 Implementation

This module provides Prometheus metrics for monitoring LLM and agent performance.

Metrics:
- Request latency (p50, p95, p99)
- Token usage
- Error rates
- Rate limiting stats
- Agent execution metrics
"""
import time
import logging
from typing import Optional, Dict, Any, Callable
from functools import wraps
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Try to import prometheus_client, fallback to mock if not available
try:
    from prometheus_client import (
        Counter, Histogram, Gauge, Info,
        generate_latest, CONTENT_TYPE_LATEST,
        CollectorRegistry, REGISTRY
    )
    PROMETHEUS_AVAILABLE = True
    logger.info("✅ prometheus_client available for metrics")
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed. Metrics will be collected in-memory only.")
    
    # Mock classes for when prometheus_client is not available
    class MockMetric:
        def __init__(self, *args, **kwargs):
            self._value = 0
            self._labels = {}
        
        def labels(self, **kwargs):
            return self
        
        def inc(self, amount=1):
            self._value += amount
        
        def dec(self, amount=1):
            self._value -= amount
        
        def set(self, value):
            self._value = value
        
        def observe(self, value):
            self._value = value
        
        def info(self, value):
            self._labels = value
    
    Counter = Histogram = Gauge = Info = MockMetric
    REGISTRY = None
    
    def generate_latest(registry=None):
        return b""
    
    CONTENT_TYPE_LATEST = "text/plain"


# Define metrics
# Request metrics
LLM_REQUEST_LATENCY = Histogram(
    'llm_request_latency_seconds',
    'LLM request latency in seconds',
    ['provider', 'model', 'agent_type'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0]
)

LLM_REQUEST_TOTAL = Counter(
    'llm_request_total',
    'Total number of LLM requests',
    ['provider', 'model', 'agent_type', 'status']
)

LLM_REQUEST_ERRORS = Counter(
    'llm_request_errors_total',
    'Total number of LLM request errors',
    ['provider', 'model', 'agent_type', 'error_type']
)

# Token metrics
LLM_TOKENS_USED = Counter(
    'llm_tokens_used_total',
    'Total tokens used in LLM requests',
    ['provider', 'model', 'agent_type', 'token_type']
)

# Rate limiting metrics
RATE_LIMIT_WAITS = Counter(
    'rate_limit_waits_total',
    'Number of times rate limiting caused a wait',
    ['provider']
)

RATE_LIMIT_TOKENS_AVAILABLE = Gauge(
    'rate_limit_tokens_available',
    'Current number of rate limit tokens available',
    ['provider']
)

LLM_CONCURRENT_REQUESTS = Gauge(
    'llm_concurrent_requests',
    'Current number of concurrent LLM requests',
    ['provider']
)

# Agent metrics
AGENT_EXECUTION_LATENCY = Histogram(
    'agent_execution_latency_seconds',
    'Agent execution latency in seconds',
    ['agent_type', 'case_id'],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
)

AGENT_EXECUTION_TOTAL = Counter(
    'agent_execution_total',
    'Total number of agent executions',
    ['agent_type', 'status']
)

AGENT_RETRY_TOTAL = Counter(
    'agent_retry_total',
    'Total number of agent retries',
    ['agent_type', 'reason']
)

# RAG metrics
RAG_RETRIEVAL_LATENCY = Histogram(
    'rag_retrieval_latency_seconds',
    'RAG retrieval latency in seconds',
    ['strategy', 'case_id'],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

RAG_DOCUMENTS_RETRIEVED = Histogram(
    'rag_documents_retrieved',
    'Number of documents retrieved per query',
    ['strategy'],
    buckets=[1, 5, 10, 20, 50, 100]
)

RAG_RELEVANCE_SCORE = Histogram(
    'rag_relevance_score',
    'RAG document relevance scores',
    ['strategy'],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

# System info
SYSTEM_INFO = Info(
    'legal_ai_vault_info',
    'Legal AI Vault system information'
)


class MetricsCollector:
    """
    Centralized metrics collector for the application.
    
    Provides methods for recording various metrics and
    generating Prometheus-compatible output.
    """
    
    def __init__(self):
        """Initialize the metrics collector."""
        self._enabled = PROMETHEUS_AVAILABLE
        self._in_memory_metrics: Dict[str, Any] = {
            "llm_requests": 0,
            "llm_errors": 0,
            "llm_latency_sum": 0.0,
            "llm_latency_count": 0,
            "tokens_used": 0,
            "agent_executions": 0,
            "agent_errors": 0,
            "rag_retrievals": 0,
        }
        logger.info(f"MetricsCollector initialized (prometheus_enabled={self._enabled})")
    
    @contextmanager
    def track_llm_request(
        self,
        provider: str = "gigachat",
        model: str = "default",
        agent_type: str = "unknown"
    ):
        """
        Context manager to track LLM request metrics.
        
        Example:
            with metrics.track_llm_request(agent_type="risk"):
                response = llm.invoke(prompt)
        """
        start_time = time.time()
        error_occurred = False
        error_type = None
        
        try:
            yield
        except Exception as e:
            error_occurred = True
            error_type = type(e).__name__
            raise
        finally:
            latency = time.time() - start_time
            
            # Record latency
            LLM_REQUEST_LATENCY.labels(
                provider=provider,
                model=model,
                agent_type=agent_type
            ).observe(latency)
            
            # Record request count
            status = "error" if error_occurred else "success"
            LLM_REQUEST_TOTAL.labels(
                provider=provider,
                model=model,
                agent_type=agent_type,
                status=status
            ).inc()
            
            # Record error if occurred
            if error_occurred:
                LLM_REQUEST_ERRORS.labels(
                    provider=provider,
                    model=model,
                    agent_type=agent_type,
                    error_type=error_type or "unknown"
                ).inc()
            
            # Update in-memory metrics
            self._in_memory_metrics["llm_requests"] += 1
            self._in_memory_metrics["llm_latency_sum"] += latency
            self._in_memory_metrics["llm_latency_count"] += 1
            if error_occurred:
                self._in_memory_metrics["llm_errors"] += 1
    
    def record_tokens_used(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        provider: str = "gigachat",
        model: str = "default",
        agent_type: str = "unknown"
    ):
        """Record token usage metrics."""
        if input_tokens > 0:
            LLM_TOKENS_USED.labels(
                provider=provider,
                model=model,
                agent_type=agent_type,
                token_type="input"
            ).inc(input_tokens)
        
        if output_tokens > 0:
            LLM_TOKENS_USED.labels(
                provider=provider,
                model=model,
                agent_type=agent_type,
                token_type="output"
            ).inc(output_tokens)
        
        self._in_memory_metrics["tokens_used"] += input_tokens + output_tokens
    
    def record_rate_limit_wait(self, provider: str = "gigachat"):
        """Record when rate limiting caused a wait."""
        RATE_LIMIT_WAITS.labels(provider=provider).inc()
    
    def update_rate_limit_stats(
        self,
        tokens_available: float,
        concurrent_requests: int,
        provider: str = "gigachat"
    ):
        """Update current rate limiting stats."""
        RATE_LIMIT_TOKENS_AVAILABLE.labels(provider=provider).set(tokens_available)
        LLM_CONCURRENT_REQUESTS.labels(provider=provider).set(concurrent_requests)
    
    @contextmanager
    def track_agent_execution(
        self,
        agent_type: str,
        case_id: str = "unknown"
    ):
        """
        Context manager to track agent execution metrics.
        
        Example:
            with metrics.track_agent_execution("risk", case_id):
                result = agent.run(state)
        """
        start_time = time.time()
        error_occurred = False
        
        try:
            yield
        except Exception:
            error_occurred = True
            raise
        finally:
            latency = time.time() - start_time
            
            # Record latency
            AGENT_EXECUTION_LATENCY.labels(
                agent_type=agent_type,
                case_id=case_id
            ).observe(latency)
            
            # Record execution count
            status = "error" if error_occurred else "success"
            AGENT_EXECUTION_TOTAL.labels(
                agent_type=agent_type,
                status=status
            ).inc()
            
            # Update in-memory metrics
            self._in_memory_metrics["agent_executions"] += 1
            if error_occurred:
                self._in_memory_metrics["agent_errors"] += 1
    
    def record_agent_retry(self, agent_type: str, reason: str = "unknown"):
        """Record an agent retry."""
        AGENT_RETRY_TOTAL.labels(
            agent_type=agent_type,
            reason=reason
        ).inc()
    
    @contextmanager
    def track_rag_retrieval(
        self,
        strategy: str = "simple",
        case_id: str = "unknown"
    ):
        """
        Context manager to track RAG retrieval metrics.
        
        Example:
            with metrics.track_rag_retrieval("hybrid", case_id) as tracker:
                docs = retriever.get_relevant(query)
                tracker.record_results(docs)
        """
        start_time = time.time()
        tracker = _RAGTracker(strategy)
        
        try:
            yield tracker
        finally:
            latency = time.time() - start_time
            
            RAG_RETRIEVAL_LATENCY.labels(
                strategy=strategy,
                case_id=case_id
            ).observe(latency)
            
            self._in_memory_metrics["rag_retrievals"] += 1
    
    def set_system_info(self, info: Dict[str, str]):
        """Set system information metrics."""
        SYSTEM_INFO.info(info)
    
    def get_metrics_output(self) -> bytes:
        """Get Prometheus-formatted metrics output."""
        if PROMETHEUS_AVAILABLE:
            return generate_latest(REGISTRY)
        return b""
    
    def get_content_type(self) -> str:
        """Get the content type for metrics output."""
        return CONTENT_TYPE_LATEST
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of collected metrics."""
        avg_latency = 0.0
        if self._in_memory_metrics["llm_latency_count"] > 0:
            avg_latency = (
                self._in_memory_metrics["llm_latency_sum"] /
                self._in_memory_metrics["llm_latency_count"]
            )
        
        return {
            "prometheus_enabled": self._enabled,
            "llm_requests_total": self._in_memory_metrics["llm_requests"],
            "llm_errors_total": self._in_memory_metrics["llm_errors"],
            "llm_avg_latency_seconds": round(avg_latency, 3),
            "tokens_used_total": self._in_memory_metrics["tokens_used"],
            "agent_executions_total": self._in_memory_metrics["agent_executions"],
            "agent_errors_total": self._in_memory_metrics["agent_errors"],
            "rag_retrievals_total": self._in_memory_metrics["rag_retrievals"],
        }


class _RAGTracker:
    """Helper class for tracking RAG retrieval results."""
    
    def __init__(self, strategy: str):
        self.strategy = strategy
        self.documents_count = 0
    
    def record_results(self, documents: list, scores: Optional[list] = None):
        """Record retrieval results."""
        self.documents_count = len(documents)
        
        RAG_DOCUMENTS_RETRIEVED.labels(
            strategy=self.strategy
        ).observe(self.documents_count)
        
        if scores:
            for score in scores:
                RAG_RELEVANCE_SCORE.labels(
                    strategy=self.strategy
                ).observe(score)


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create the global metrics collector instance."""
    global _metrics_collector
    
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    
    return _metrics_collector


def track_llm_call(
    provider: str = "gigachat",
    model: str = "default",
    agent_type: str = "unknown"
) -> Callable:
    """
    Decorator to track LLM call metrics.
    
    Example:
        @track_llm_call(agent_type="risk")
        def analyze_risk(self, state):
            return self.llm.invoke(prompt)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            with collector.track_llm_request(provider, model, agent_type):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def track_agent(agent_type: str) -> Callable:
    """
    Decorator to track agent execution metrics.
    
    Example:
        @track_agent("risk")
        def run(self, state):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            collector = get_metrics_collector()
            case_id = "unknown"
            
            # Try to extract case_id from args
            if args and hasattr(args[0], 'get'):
                case_id = args[0].get('case_id', 'unknown')
            elif 'state' in kwargs and hasattr(kwargs['state'], 'get'):
                case_id = kwargs['state'].get('case_id', 'unknown')
            
            with collector.track_agent_execution(agent_type, case_id):
                return func(*args, **kwargs)
        return wrapper
    return decorator

