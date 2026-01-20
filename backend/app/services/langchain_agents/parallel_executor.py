"""
Parallel Executor - Унифицированный модуль параллельного выполнения

Объединяет функциональность из:
- parallel_execution.py
- parallel_execution_v2.py

Предоставляет:
- LangGraph-native fan-out/fan-in паттерны
- Reducer для слияния результатов
- State-safe параллельное выполнение
- Улучшенная обработка ошибок
"""
from typing import Dict, Any, List, Optional, Callable, Sequence
from langgraph.types import Send
from app.services.langchain_agents.state import AnalysisState
from app.config import config
import logging
import time
import os

logger = logging.getLogger(__name__)


# =============================================================================
# Конфигурация таймаутов агентов (секунды)
# =============================================================================

AGENT_TIMEOUTS: Dict[str, int] = {
    "document_classifier": 60,
    "timeline": 120,
    "key_facts": 120,
    "discrepancy": 180,
    "entity_extraction": 120,
    "risk": 180,
    "summary": 120,
    "privilege_check": 90,
    "legal_analysis": 180,
}

DEFAULT_AGENT_TIMEOUT = 120


# =============================================================================
# Утилиты
# =============================================================================

def should_use_langgraph_parallel() -> bool:
    """
    Проверить, следует ли использовать LangGraph параллельное выполнение.
    
    Контролируется переменной окружения USE_LANGGRAPH_PARALLEL.
    По умолчанию: True
    """
    return os.getenv("USE_LANGGRAPH_PARALLEL", "true").lower() == "true"


def get_agent_timeout(agent_name: str) -> int:
    """
    Получить таймаут для агента
    
    Args:
        agent_name: Имя агента
        
    Returns:
        Таймаут в секундах
    """
    return AGENT_TIMEOUTS.get(agent_name, DEFAULT_AGENT_TIMEOUT)


# =============================================================================
# Создание Send объектов для параллельного выполнения
# =============================================================================

def create_parallel_sends(
    state: AnalysisState,
    agent_names: List[str],
    target_node: str = "execute_single_agent",
    agent_registry: Optional[Dict[str, Any]] = None
) -> List[Send]:
    """
    Создать Send объекты для параллельного выполнения агентов.
    
    Использует LangGraph fan-out паттерн вместо ThreadPoolExecutor.
    
    Args:
        state: Текущее состояние анализа
        agent_names: Список имён агентов для выполнения
        target_node: Имя узла для выполнения (default: execute_single_agent)
        agent_registry: Опциональный реестр агентов для валидации
        
    Returns:
        Список Send объектов для параллельного выполнения
    """
    sends = []
    case_id = state.get("case_id", "unknown")
    
    for agent_name in agent_names:
        # Проверить, не завершён ли уже агент
        result_key = f"{agent_name}_result"
        ref_key = f"{agent_name}_ref"
        
        if state.get(result_key) is not None or state.get(ref_key) is not None:
            logger.debug(f"Skipping {agent_name} - result already exists")
            continue
        
        # Проверить наличие в реестре (если передан)
        if agent_registry and agent_name not in agent_registry:
            logger.warning(f"Agent {agent_name} not in registry, skipping")
            continue
        
        # Создать копию state для этого агента
        agent_state = dict(state)
        agent_state["current_agent"] = agent_name
        agent_state["agent_timeout"] = get_agent_timeout(agent_name)
        
        # Создать Send к целевому узлу
        send = Send(target_node, agent_state)
        sends.append(send)
        
        logger.debug(f"Created Send for {agent_name} agent (case {case_id})")
    
    logger.info(f"Created {len(sends)} parallel Sends for case {case_id}")
    return sends


# =============================================================================
# Слияние результатов параллельного выполнения
# =============================================================================

def merge_parallel_results(
    states: Sequence[AnalysisState],
    base_state: Optional[AnalysisState] = None
) -> AnalysisState:
    """
    Reducer функция для слияния результатов параллельных агентов.
    
    Это fan-in часть fan-out/fan-in паттерна.
    
    Args:
        states: Последовательность состояний из параллельных выполнений
        base_state: Опциональное базовое состояние для слияния
        
    Returns:
        Объединённое состояние со всеми результатами агентов
    """
    if not states:
        return base_state or {}
    
    # Начать с базового состояния или первого состояния
    if base_state:
        merged = dict(base_state)
    else:
        merged = dict(states[0])
    
    # Отслеживать что мы объединили
    merged_agents = []
    all_errors = list(merged.get("errors", []))
    all_completed_steps = set(merged.get("completed_steps", []))
    merged_metadata = dict(merged.get("metadata", {}))
    
    # Обработать каждое состояние
    for state in states:
        if state is None:
            continue
        
        agent_name = state.get("current_agent")
        if agent_name:
            merged_agents.append(agent_name)
        
        # Объединить результаты агента (результат или ссылка в Store)
        for key, value in state.items():
            if (key.endswith("_result") or key.endswith("_ref") or key.endswith("_summary")) and value is not None:
                merged[key] = value
        
        # Объединить ошибки (дедупликация по имени агента)
        if "errors" in state:
            existing_agents = {e.get("agent") for e in all_errors if isinstance(e, dict)}
            for error in state["errors"]:
                if isinstance(error, dict) and error.get("agent") not in existing_agents:
                    all_errors.append(error)
                elif isinstance(error, str) and error not in all_errors:
                    all_errors.append(error)
        
        # Объединить completed_steps
        if "completed_steps" in state:
            all_completed_steps.update(state.get("completed_steps", []))
        
        # Объединить metadata
        if "metadata" in state:
            state_metadata = state.get("metadata", {})
            for key, value in state_metadata.items():
                if key not in merged_metadata:
                    merged_metadata[key] = value
                elif isinstance(merged_metadata[key], dict) and isinstance(value, dict):
                    merged_metadata[key].update(value)
                elif isinstance(merged_metadata[key], list) and isinstance(value, list):
                    merged_metadata[key].extend(value)
    
    # Применить объединённые коллекции
    merged["errors"] = all_errors
    merged["completed_steps"] = list(all_completed_steps)
    merged["metadata"] = merged_metadata
    
    logger.info(f"Merged results from {len(merged_agents)} parallel agents: {merged_agents}")
    return merged


# =============================================================================
# Класс ParallelAgentExecutor
# =============================================================================

class ParallelAgentExecutor:
    """
    Исполнитель для параллельного запуска агентов с использованием LangGraph паттернов.
    
    Предоставляет высокоуровневый интерфейс для параллельного выполнения
    с встроенной обработкой ошибок и слиянием результатов.
    """
    
    def __init__(
        self,
        agent_registry: Dict[str, Callable],
        max_parallel: Optional[int] = None
    ):
        """
        Инициализация исполнителя.
        
        Args:
            agent_registry: Словарь имя агента → функция
            max_parallel: Максимальное число параллельных агентов (default из config)
        """
        self.agent_registry = agent_registry
        self.max_parallel = max_parallel or getattr(config, 'AGENT_MAX_PARALLEL', 5)
    
    def prepare_sends(
        self,
        state: AnalysisState,
        requested_agents: List[str]
    ) -> List[Send]:
        """
        Подготовить Send объекты для запрошенных агентов.
        
        Args:
            state: Текущее состояние
            requested_agents: Список имён агентов для запуска
            
        Returns:
            Список Send объектов
        """
        # Фильтровать по доступным агентам
        available = [
            name for name in requested_agents
            if name in self.agent_registry
        ]
        
        # Фильтровать по ещё не завершённым
        to_run = [
            name for name in available
            if state.get(f"{name}_result") is None and state.get(f"{name}_ref") is None
        ]
        
        # Ограничить до max_parallel
        if len(to_run) > self.max_parallel:
            logger.warning(
                f"Limiting parallel agents from {len(to_run)} to {self.max_parallel}"
            )
            to_run = to_run[:self.max_parallel]
        
        return create_parallel_sends(
            state, to_run, "execute_single_agent", self.agent_registry
        )
    
    def execute_agent(self, state: AnalysisState) -> AnalysisState:
        """
        Выполнить один агент (используется как target для Send).
        
        Args:
            state: Состояние с установленным current_agent
            
        Returns:
            Обновлённое состояние с результатом агента
        """
        agent_name = state.get("current_agent")
        if not agent_name:
            logger.error("No current_agent in state")
            return state
        
        agent_func = self.agent_registry.get(agent_name)
        if not agent_func:
            logger.error(f"Agent function not found: {agent_name}")
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": agent_name,
                "error": f"Agent function not found: {agent_name}"
            })
            return new_state
        
        start_time = time.time()
        timeout = state.get("agent_timeout", DEFAULT_AGENT_TIMEOUT)
        
        try:
            logger.info(f"Executing {agent_name} agent (timeout={timeout}s)")
            result_state = agent_func(state)
            
            duration = time.time() - start_time
            logger.info(f"Completed {agent_name} agent in {duration:.2f}s")
            
            return result_state
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"Error in {agent_name} agent after {duration:.2f}s: {e}",
                exc_info=True
            )
            
            new_state = dict(state)
            new_state.setdefault("errors", []).append({
                "agent": agent_name,
                "error": str(e),
                "duration": duration
            })
            return new_state


# =============================================================================
# Factory функции для создания узлов графа
# =============================================================================

def create_fanout_node(
    agent_registry: Dict[str, Callable],
    independent_agents: List[str]
) -> Callable:
    """
    Создать fan-out узел, который отправляет независимые агенты на параллельное выполнение.
    
    Args:
        agent_registry: Словарь имя агента → функция
        independent_agents: Список агентов, которые могут выполняться параллельно
        
    Returns:
        Функция, создающая Send объекты для параллельного выполнения
    """
    def fanout_node(state: AnalysisState) -> List[Send]:
        """Dispatch independent agents in parallel."""
        analysis_types = state.get("analysis_types", [])
        
        # Фильтровать по запрошенным независимым агентам
        agents_to_run = [
            name for name in independent_agents
            if name in analysis_types and name in agent_registry
        ]
        
        # Фильтровать по ещё не завершённым
        agents_to_run = [
            name for name in agents_to_run
            if state.get(f"{name}_result") is None and state.get(f"{name}_ref") is None
        ]
        
        if not agents_to_run:
            logger.info("No independent agents to dispatch")
            return []
        
        return create_parallel_sends(state, agents_to_run, "execute_single_agent", agent_registry)
    
    return fanout_node


def create_reducer_node() -> Callable:
    """
    Создать reducer узел, который сливает результаты параллельных выполнений.
    
    Returns:
        Функция, сливающая параллельные состояния
    """
    def reducer_node(states: Sequence[AnalysisState]) -> AnalysisState:
        """Merge results from parallel agents."""
        return merge_parallel_results(states)
    
    return reducer_node


# =============================================================================
# Backward compatibility exports
# =============================================================================

# Алиасы для обратной совместимости с parallel_execution.py
create_parallel_sends_v1 = create_parallel_sends
merge_parallel_results_v1 = merge_parallel_results

# Алиасы для обратной совместимости с parallel_execution_v2.py
create_parallel_sends_v2 = create_parallel_sends
merge_parallel_results_v2 = merge_parallel_results


