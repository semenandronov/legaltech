"""
Chat Metrics - Метрики для мониторинга чата

Предоставляет:
- Счётчики запросов
- Гистограммы латентности
- Метрики по агентам
- Метрики ошибок
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import time
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Метрики (простая in-memory реализация)
# =============================================================================

@dataclass
class MetricValue:
    """Значение метрики"""
    count: int = 0
    total: float = 0.0
    min_value: float = float('inf')
    max_value: float = float('-inf')
    last_value: float = 0.0
    last_updated: Optional[datetime] = None
    
    def record(self, value: float) -> None:
        """Записать значение"""
        self.count += 1
        self.total += value
        self.min_value = min(self.min_value, value)
        self.max_value = max(self.max_value, value)
        self.last_value = value
        self.last_updated = datetime.utcnow()
    
    @property
    def avg(self) -> float:
        """Среднее значение"""
        return self.total / self.count if self.count > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь"""
        return {
            "count": self.count,
            "total": self.total,
            "avg": self.avg,
            "min": self.min_value if self.count > 0 else None,
            "max": self.max_value if self.count > 0 else None,
            "last": self.last_value,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None
        }


@dataclass
class ChatMetrics:
    """
    Метрики чата.
    
    Собирает статистику по:
    - Количеству запросов
    - Времени ответа
    - Использованию режимов
    - Ошибкам
    """
    
    # Счётчики запросов по режимам
    requests_total: Dict[str, int] = field(default_factory=dict)
    
    # Латентность по режимам (секунды)
    latency: Dict[str, MetricValue] = field(default_factory=dict)
    
    # Ошибки по типам
    errors: Dict[str, int] = field(default_factory=dict)
    
    # Агенты
    agent_executions: Dict[str, MetricValue] = field(default_factory=dict)
    
    # Классификация
    classifications: Dict[str, int] = field(default_factory=dict)
    
    # Внешние сервисы
    external_calls: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    # Обратная связь по ответам ассистента
    feedback: Dict[str, int] = field(default_factory=dict)
    # Mode-specific eval counters
    mode_evals: Dict[str, Dict[str, int]] = field(default_factory=dict)
    route_outcomes: Dict[str, Dict[str, int]] = field(default_factory=dict)
    prompt_profiles: Dict[str, Dict[str, int]] = field(default_factory=dict)
    
    def record_request(self, mode: str) -> None:
        """
        Записать запрос
        
        Args:
            mode: Режим (rag, draft, editor, agent)
        """
        self.requests_total[mode] = self.requests_total.get(mode, 0) + 1
        logger.debug(f"Recorded request: mode={mode}")
    
    def record_latency(self, mode: str, seconds: float) -> None:
        """
        Записать латентность
        
        Args:
            mode: Режим
            seconds: Время в секундах
        """
        if mode not in self.latency:
            self.latency[mode] = MetricValue()
        self.latency[mode].record(seconds)
        logger.debug(f"Recorded latency: mode={mode}, seconds={seconds:.3f}")
    
    def record_error(self, error_type: str) -> None:
        """
        Записать ошибку
        
        Args:
            error_type: Тип ошибки
        """
        self.errors[error_type] = self.errors.get(error_type, 0) + 1
        logger.debug(f"Recorded error: type={error_type}")
    
    def record_agent_execution(self, agent_name: str, seconds: float) -> None:
        """
        Записать выполнение агента
        
        Args:
            agent_name: Имя агента
            seconds: Время выполнения
        """
        if agent_name not in self.agent_executions:
            self.agent_executions[agent_name] = MetricValue()
        self.agent_executions[agent_name].record(seconds)
        logger.debug(f"Recorded agent execution: agent={agent_name}, seconds={seconds:.3f}")
    
    def record_classification(self, label: str) -> None:
        """
        Записать результат классификации
        
        Args:
            label: Метка (task/question)
        """
        self.classifications[label] = self.classifications.get(label, 0) + 1
        logger.debug(f"Recorded classification: label={label}")
    
    def record_external_call(
        self,
        service: str,
        success: bool = True,
        reason: Optional[str] = None
    ) -> None:
        """
        Записать вызов внешнего сервиса
        
        Args:
            service: Имя сервиса (garant, llm, etc.)
            success: Успешен ли вызов
            reason: Причина неудачи (если success=False)
        """
        if service not in self.external_calls:
            self.external_calls[service] = {"success": 0, "failure": 0}
        
        if success:
            self.external_calls[service]["success"] += 1
        else:
            self.external_calls[service]["failure"] += 1
            if reason:
                key = f"failure:{reason}"
                self.external_calls[service][key] = self.external_calls[service].get(key, 0) + 1
        
        logger.debug(f"Recorded external call: service={service}, success={success}")

    def record_feedback(self, rating: str) -> None:
        """Записать пользовательскую оценку ответа ассистента."""
        key = (rating or "unknown").strip().lower() or "unknown"
        self.feedback[key] = self.feedback.get(key, 0) + 1
        logger.debug("Recorded feedback: rating=%s", key)

    def record_mode_eval(self, mode: str, metric: str, success: bool) -> None:
        """Record lightweight mode-specific eval counters."""
        mode_key = (mode or "unknown").strip().lower() or "unknown"
        metric_key = (metric or "unknown").strip().lower() or "unknown"
        if mode_key not in self.mode_evals:
            self.mode_evals[mode_key] = {}
        key = f"{metric_key}:{'pass' if success else 'fail'}"
        self.mode_evals[mode_key][key] = self.mode_evals[mode_key].get(key, 0) + 1
        logger.debug("Recorded mode eval: mode=%s metric=%s success=%s", mode_key, metric_key, success)

    def record_route_outcome(self, predicted_route: str, actual_route: str) -> None:
        pred = (predicted_route or "unknown").strip().lower() or "unknown"
        act = (actual_route or "unknown").strip().lower() or "unknown"
        if pred not in self.route_outcomes:
            self.route_outcomes[pred] = {}
        self.route_outcomes[pred][act] = self.route_outcomes[pred].get(act, 0) + 1
        logger.debug("Recorded route outcome: predicted=%s actual=%s", pred, act)

    def record_prompt_profile(self, profile_id: str, metric: str, success: bool) -> None:
        profile = (profile_id or "legacy_default").strip().lower() or "legacy_default"
        metric_key = (metric or "unknown").strip().lower() or "unknown"
        if profile not in self.prompt_profiles:
            self.prompt_profiles[profile] = {}
        key = f"{metric_key}:{'pass' if success else 'fail'}"
        self.prompt_profiles[profile][key] = self.prompt_profiles[profile].get(key, 0) + 1
        logger.debug("Recorded prompt profile metric: profile=%s metric=%s success=%s", profile, metric_key, success)

    def get_route_kpis(self) -> Dict[str, Any]:
        labels = set(self.route_outcomes.keys())
        for actuals in self.route_outcomes.values():
            labels.update(actuals.keys())
        metrics: Dict[str, Dict[str, float]] = {}
        for label in sorted(labels):
            tp = self.route_outcomes.get(label, {}).get(label, 0)
            fp = sum(
                count
                for pred, actuals in self.route_outcomes.items()
                if pred == label
                for act, count in actuals.items()
                if act != label
            )
            fn = sum(
                actuals.get(label, 0)
                for pred, actuals in self.route_outcomes.items()
                if pred != label
            )
            precision = tp / (tp + fp) if (tp + fp) else 0.0
            recall = tp / (tp + fn) if (tp + fn) else 0.0
            f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
            metrics[label] = {
                "tp": float(tp),
                "fp": float(fp),
                "fn": float(fn),
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        return {"confusion_matrix": self.route_outcomes, "per_label": metrics}
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Получить сводку метрик
        
        Returns:
            Словарь с метриками
        """
        return {
            "requests_total": self.requests_total,
            "latency": {k: v.to_dict() for k, v in self.latency.items()},
            "errors": self.errors,
            "agent_executions": {k: v.to_dict() for k, v in self.agent_executions.items()},
            "classifications": self.classifications,
            "external_calls": self.external_calls,
            "feedback": self.feedback,
            "mode_evals": self.mode_evals,
            "routing_kpis": self.get_route_kpis(),
            "prompt_profiles": self.prompt_profiles,
        }
    
    def reset(self) -> None:
        """Сбросить все метрики"""
        self.requests_total.clear()
        self.latency.clear()
        self.errors.clear()
        self.agent_executions.clear()
        self.classifications.clear()
        self.external_calls.clear()
        self.feedback.clear()
        self.mode_evals.clear()
        self.route_outcomes.clear()
        self.prompt_profiles.clear()


# =============================================================================
# Глобальный экземпляр метрик
# =============================================================================

_metrics: Optional[ChatMetrics] = None


def get_metrics() -> ChatMetrics:
    """Получить глобальный экземпляр метрик"""
    global _metrics
    if _metrics is None:
        _metrics = ChatMetrics()
    return _metrics


# =============================================================================
# Context Manager для измерения времени
# =============================================================================

class Timer:
    """
    Context manager для измерения времени.
    
    Пример использования:
    ```python
    with Timer() as timer:
        # код
    print(f"Elapsed: {timer.elapsed}s")
    ```
    """
    
    def __init__(self):
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
    
    def __enter__(self) -> "Timer":
        self.start_time = time.time()
        return self
    
    def __exit__(self, *args) -> None:
        self.end_time = time.time()
    
    @property
    def elapsed(self) -> float:
        """Прошедшее время в секундах"""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time


class MetricTimer:
    """
    Context manager для измерения времени с автоматической записью в метрики.
    
    Пример использования:
    ```python
    with MetricTimer("rag") as timer:
        # код
    # Автоматически записывается в metrics.latency["rag"]
    ```
    """
    
    def __init__(self, mode: str, metrics: Optional[ChatMetrics] = None):
        self.mode = mode
        self.metrics = metrics or get_metrics()
        self.timer = Timer()
    
    def __enter__(self) -> "MetricTimer":
        self.timer.__enter__()
        self.metrics.record_request(self.mode)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.timer.__exit__(exc_type, exc_val, exc_tb)
        self.metrics.record_latency(self.mode, self.timer.elapsed)
        
        if exc_type is not None:
            error_type = exc_type.__name__ if exc_type else "unknown"
            self.metrics.record_error(f"{self.mode}:{error_type}")
    
    @property
    def elapsed(self) -> float:
        """Прошедшее время"""
        return self.timer.elapsed


# =============================================================================
# Prometheus-совместимые метрики (заглушки для будущей интеграции)
# =============================================================================

def init_prometheus_metrics():
    """
    Инициализация Prometheus метрик.
    
    TODO: Интегрировать с prometheus_client когда будет готова инфраструктура.
    
    Планируемые метрики:
    - chat_requests_total (Counter) - labels: mode
    - chat_latency_seconds (Histogram) - labels: mode
    - agent_executions_total (Counter) - labels: agent_name
    - agent_execution_seconds (Histogram) - labels: agent_name
    - classification_total (Counter) - labels: label
    """
    logger.info("Prometheus metrics initialization placeholder")
    # TODO: Реализовать когда prometheus_client будет добавлен в зависимости
    pass


