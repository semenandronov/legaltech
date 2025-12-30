"""Graph monitoring and metrics for LangGraph execution"""
from typing import Dict, Any, List, Optional
from app.services.langchain_agents.state import AnalysisState
from collections import defaultdict
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class NodeMetrics:
    """Метрики выполнения узла графа"""
    node_name: str
    execution_count: int = 0
    total_execution_time: float = 0.0
    min_execution_time: Optional[float] = None
    max_execution_time: Optional[float] = 0.0
    error_count: int = 0
    last_execution_time: Optional[datetime] = None
    errors: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def average_execution_time(self) -> float:
        """Среднее время выполнения"""
        if self.execution_count == 0:
            return 0.0
        return self.total_execution_time / self.execution_count
    
    def add_execution(self, execution_time: float, error: Optional[Exception] = None):
        """Добавить метрику выполнения"""
        self.execution_count += 1
        self.total_execution_time += execution_time
        self.last_execution_time = datetime.now()
        
        if self.min_execution_time is None or execution_time < self.min_execution_time:
            self.min_execution_time = execution_time
        if execution_time > self.max_execution_time:
            self.max_execution_time = execution_time
        
        if error:
            self.error_count += 1
            self.errors.append({
                "timestamp": datetime.now().isoformat(),
                "error_type": type(error).__name__,
                "error_message": str(error)
            })
            # Ограничиваем количество сохраненных ошибок
            if len(self.errors) > 10:
                self.errors = self.errors[-10:]
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразовать в словарь для сериализации"""
        return {
            "node_name": self.node_name,
            "execution_count": self.execution_count,
            "total_execution_time": self.total_execution_time,
            "average_execution_time": self.average_execution_time,
            "min_execution_time": self.min_execution_time,
            "max_execution_time": self.max_execution_time,
            "error_count": self.error_count,
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
            "errors": self.errors[-5:] if self.errors else []  # Последние 5 ошибок
        }


class GraphMonitor:
    """Мониторинг выполнения графа LangGraph"""
    
    def __init__(self):
        self.node_metrics: Dict[str, NodeMetrics] = {}
        self.case_metrics: Dict[str, Dict[str, Any]] = {}
        self.start_times: Dict[str, float] = {}  # case_id -> start_time
        logger.info("GraphMonitor initialized")
    
    def start_node_execution(self, case_id: str, node_name: str):
        """Начать отслеживание выполнения узла"""
        key = f"{case_id}:{node_name}"
        self.start_times[key] = time.time()
        logger.debug(f"[Monitor] Started tracking node {node_name} for case {case_id}")
    
    def end_node_execution(
        self,
        case_id: str,
        node_name: str,
        error: Optional[Exception] = None
    ):
        """Завершить отслеживание выполнения узла"""
        key = f"{case_id}:{node_name}"
        start_time = self.start_times.pop(key, None)
        
        if start_time is None:
            logger.warning(f"[Monitor] No start time found for node {node_name} in case {case_id}")
            return
        
        execution_time = time.time() - start_time
        
        # Обновляем метрики узла
        if node_name not in self.node_metrics:
            self.node_metrics[node_name] = NodeMetrics(node_name=node_name)
        
        self.node_metrics[node_name].add_execution(execution_time, error)
        
        # Обновляем метрики для case
        if case_id not in self.case_metrics:
            self.case_metrics[case_id] = {
                "case_id": case_id,
                "nodes_executed": [],
                "total_execution_time": 0.0,
                "start_time": None,
                "end_time": None,
                "error_count": 0
            }
        
        case_metric = self.case_metrics[case_id]
        case_metric["nodes_executed"].append({
            "node_name": node_name,
            "execution_time": execution_time,
            "timestamp": datetime.now().isoformat(),
            "error": str(error) if error else None
        })
        case_metric["total_execution_time"] += execution_time
        case_metric["error_count"] += (1 if error else 0)
        
        logger.info(
            f"[Monitor] Node {node_name} executed in {execution_time:.2f}s "
            f"(case: {case_id}, error: {'yes' if error else 'no'})"
        )
    
    def start_case_execution(self, case_id: str):
        """Начать отслеживание выполнения дела"""
        if case_id not in self.case_metrics:
            self.case_metrics[case_id] = {
                "case_id": case_id,
                "nodes_executed": [],
                "total_execution_time": 0.0,
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "error_count": 0
            }
        else:
            self.case_metrics[case_id]["start_time"] = datetime.now().isoformat()
        logger.info(f"[Monitor] Started tracking case {case_id}")
    
    def end_case_execution(self, case_id: str):
        """Завершить отслеживание выполнения дела"""
        if case_id in self.case_metrics:
            self.case_metrics[case_id]["end_time"] = datetime.now().isoformat()
            logger.info(
                f"[Monitor] Case {case_id} completed: "
                f"{len(self.case_metrics[case_id]['nodes_executed'])} nodes, "
                f"{self.case_metrics[case_id]['total_execution_time']:.2f}s total"
            )
    
    def get_node_metrics(self, node_name: Optional[str] = None) -> Dict[str, Any]:
        """Получить метрики узла(ов)"""
        if node_name:
            if node_name in self.node_metrics:
                return self.node_metrics[node_name].to_dict()
            return {}
        
        # Возвращаем метрики всех узлов
        return {
            name: metrics.to_dict()
            for name, metrics in self.node_metrics.items()
        }
    
    def get_case_metrics(self, case_id: Optional[str] = None) -> Dict[str, Any]:
        """Получить метрики дела(дел)"""
        if case_id:
            return self.case_metrics.get(case_id, {})
        
        # Возвращаем метрики всех дел
        return self.case_metrics
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Получить сводку производительности"""
        if not self.node_metrics:
            return {
                "total_nodes": 0,
                "total_executions": 0,
                "total_errors": 0,
                "average_execution_time": 0.0,
                "slowest_nodes": [],
                "nodes_with_errors": []
            }
        
        total_executions = sum(m.execution_count for m in self.node_metrics.values())
        total_errors = sum(m.error_count for m in self.node_metrics.values())
        total_time = sum(m.total_execution_time for m in self.node_metrics.values())
        average_time = total_time / total_executions if total_executions > 0 else 0.0
        
        # Самые медленные узлы
        slowest_nodes = sorted(
            self.node_metrics.values(),
            key=lambda m: m.average_execution_time,
            reverse=True
        )[:5]
        
        # Узлы с ошибками
        nodes_with_errors = [
            m.node_name
            for m in self.node_metrics.values()
            if m.error_count > 0
        ]
        
        return {
            "total_nodes": len(self.node_metrics),
            "total_executions": total_executions,
            "total_errors": total_errors,
            "average_execution_time": average_time,
            "slowest_nodes": [m.to_dict() for m in slowest_nodes],
            "nodes_with_errors": nodes_with_errors
        }
    
    def clear_metrics(self, case_id: Optional[str] = None):
        """Очистить метрики"""
        if case_id:
            self.case_metrics.pop(case_id, None)
            # Удаляем start_times для этого case
            keys_to_remove = [k for k in self.start_times.keys() if k.startswith(f"{case_id}:")]
            for key in keys_to_remove:
                del self.start_times[key]
            logger.info(f"[Monitor] Cleared metrics for case {case_id}")
        else:
            self.node_metrics.clear()
            self.case_metrics.clear()
            self.start_times.clear()
            logger.info("[Monitor] Cleared all metrics")


# Global monitor instance
_global_monitor: Optional[GraphMonitor] = None


def get_graph_monitor() -> GraphMonitor:
    """Получить глобальный экземпляр монитора"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = GraphMonitor()
    return _global_monitor


def monitor_node_execution(node_name: str):
    """
    Декоратор для мониторинга выполнения узла графа
    
    Usage:
        @monitor_node_execution("timeline")
        def timeline_node(state: AnalysisState) -> AnalysisState:
            # ... node implementation
    """
    def decorator(node_func):
        def wrapped_node(state: AnalysisState) -> AnalysisState:
            case_id = state.get("case_id", "unknown")
            monitor = get_graph_monitor()
            error = None
            
            try:
                monitor.start_node_execution(case_id, node_name)
                result_state = node_func(state)
                return result_state
            except Exception as e:
                error = e
                raise
            finally:
                monitor.end_node_execution(case_id, node_name, error)
        
        wrapped_node.__name__ = node_func.__name__
        wrapped_node.__doc__ = node_func.__doc__
        return wrapped_node
    
    return decorator

