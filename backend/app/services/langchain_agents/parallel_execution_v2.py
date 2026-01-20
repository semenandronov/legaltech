"""Parallel Execution v2 using LangGraph Send/Command (replaces ThreadPoolExecutor)"""
from typing import Dict, Any, List, Optional, Sequence
from langgraph.graph import StateGraph
from langgraph.types import Send
from app.services.langchain_agents.state import AnalysisState
from app.config import config
import logging

logger = logging.getLogger(__name__)

# Agent timeout configuration (seconds)
AGENT_TIMEOUTS = {
    "document_classifier": 60,
    "timeline": 120,
    "key_facts": 120,
    "discrepancy": 180,
    "entity_extraction": 120,
    "risk": 180,
    "summary": 120,
}

# Default timeout
DEFAULT_AGENT_TIMEOUT = 120


def create_parallel_sends_v2(
    state: AnalysisState,
    agent_names: List[str],
    agent_registry: Dict[str, Any]
) -> List[Send]:
    """
    Создать Send объекты для параллельного выполнения агентов
    
    Args:
        state: Текущее состояние анализа
        agent_names: Список имен агентов для выполнения
        agent_registry: Реестр функций агентов
    
    Returns:
        Список Send объектов для параллельного выполнения
    """
    sends = []
    case_id = state.get("case_id", "unknown")
    
    for agent_name in agent_names:
        # Проверить, не завершен ли уже агент
        result_key = f"{agent_name}_result"
        ref_key = f"{agent_name}_ref"
        
        if state.get(result_key) is not None or state.get(ref_key) is not None:
            logger.debug(f"Skipping {agent_name} - result already exists")
            continue
        
        # Проверить, есть ли функция агента
        if agent_name not in agent_registry:
            logger.warning(f"Agent {agent_name} not in registry, skipping")
            continue
        
        # Создать копию state для этого агента
        agent_state = dict(state)
        agent_state["current_agent"] = agent_name
        agent_state["agent_timeout"] = AGENT_TIMEOUTS.get(agent_name, DEFAULT_AGENT_TIMEOUT)
        
        # Создать Send к узлу execute_single_agent
        send = Send("execute_single_agent", agent_state)
        sends.append(send)
        
        logger.debug(f"Created Send for {agent_name} agent (case {case_id})")
    
    logger.info(f"Created {len(sends)} parallel Sends for case {case_id}")
    return sends


def merge_parallel_results_v2(
    states: Sequence[AnalysisState],
    base_state: Optional[AnalysisState] = None
) -> AnalysisState:
    """
    Reducer функция для слияния результатов параллельных агентов
    
    Args:
        states: Последовательность состояний из параллельных выполнений
        base_state: Опциональное базовое состояние для слияния
    
    Returns:
        Объединенное состояние со всеми результатами агентов
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
        
        # Объединить результат агента (результат или ссылка в Store)
        for key, value in state.items():
            if (key.endswith("_result") or key.endswith("_ref")) and value is not None:
                merged[key] = value
        
        # Объединить summary если есть
        for key, value in state.items():
            if key.endswith("_summary") and value is not None:
                merged[key] = value
        
        # Объединить ошибки (дедупликация по имени агента)
        if "errors" in state:
            existing_agents = {e.get("agent") for e in all_errors}
            for error in state["errors"]:
                if error.get("agent") not in existing_agents:
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
    
    # Применить объединенные коллекции
    merged["errors"] = all_errors
    merged["completed_steps"] = list(all_completed_steps)
    merged["metadata"] = merged_metadata
    
    logger.info(f"Merged results from {len(merged_agents)} parallel agents: {merged_agents}")
    return merged










































