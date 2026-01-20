"""LangChain agents for Legal AI Vault multi-agent analysis system

Архитектура:
- simplified_graph.py — Упрощённый граф с 6 основными агентами
- simplified_coordinator.py — Координатор для запуска анализа
- simplified_router.py — Rule-based маршрутизация
- core_agents.py — Единый источник правды для определений агентов
- result_validator.py — Валидация результатов

Legacy (для обратной совместимости):
- coordinator.py — Старый координатор (сложный)
- graph.py — Старый граф (много узлов)
- supervisor.py — Старый supervisor
"""
# Новая упрощённая архитектура (рекомендуется)
from app.services.langchain_agents.simplified_coordinator import SimplifiedAgentCoordinator
from app.services.langchain_agents.simplified_graph import create_simplified_graph
from app.services.langchain_agents.simplified_router import SimplifiedRouter, classify_request
from app.services.langchain_agents.core_agents import (
    CORE_AGENTS,
    ALL_AGENTS,
    AGENT_DEFINITIONS,
    DEPENDENCIES,
    validate_analysis_types,
    get_agents_with_dependencies,
)
from app.services.langchain_agents.result_validator import ResultValidator, ValidationLevel

# Legacy (для обратной совместимости)
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.supervisor import route_to_agent, create_supervisor_agent
from app.services.langchain_agents.agent_factory import create_legal_agent
from app.services.langchain_agents.planning_agent import PlanningAgent

__all__ = [
    # Новая архитектура
    "SimplifiedAgentCoordinator",
    "create_simplified_graph",
    "SimplifiedRouter",
    "classify_request",
    "CORE_AGENTS",
    "ALL_AGENTS",
    "AGENT_DEFINITIONS",
    "DEPENDENCIES",
    "validate_analysis_types",
    "get_agents_with_dependencies",
    "ResultValidator",
    "ValidationLevel",
    
    # Legacy
    "AgentCoordinator",
    "create_analysis_graph",
    "AnalysisState",
    "route_to_agent",
    "create_supervisor_agent",
    "create_legal_agent",
    "PlanningAgent",
]
