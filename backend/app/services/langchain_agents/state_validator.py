"""State validation utilities for AnalysisState"""
from typing import Dict, Any, List, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.planning_tools import validate_analysis_types
import logging

logger = logging.getLogger(__name__)


def validate_state(state: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Валидирует AnalysisState и возвращает список ошибок.
    
    Args:
        state: Словарь состояния для валидации
    
    Returns:
        Tuple (is_valid, errors_list)
    """
    errors = []
    
    # Валидация case_id
    case_id = state.get("case_id")
    if not case_id or not isinstance(case_id, str) or not case_id.strip():
        errors.append("case_id must be a non-empty string")
    
    # Валидация analysis_types
    analysis_types = state.get("analysis_types", [])
    if not isinstance(analysis_types, list):
        errors.append("analysis_types must be a list")
    else:
        is_valid, invalid_types = validate_analysis_types(analysis_types)
        if not is_valid:
            errors.append(f"Invalid analysis types: {invalid_types}")
    
    # Валидация metadata
    metadata = state.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("metadata must be a dictionary")
    
    # Валидация errors
    errors_list = state.get("errors", [])
    if not isinstance(errors_list, list):
        errors.append("errors must be a list")
    
    # Валидация completed_steps
    completed_steps = state.get("completed_steps", [])
    if not isinstance(completed_steps, list):
        errors.append("completed_steps must be a list")
    
    # Валидация plan_goals
    plan_goals = state.get("plan_goals", [])
    if not isinstance(plan_goals, list):
        errors.append("plan_goals must be a list")
    
    # Валидация current_plan
    current_plan = state.get("current_plan", [])
    if not isinstance(current_plan, list):
        errors.append("current_plan must be a list")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def validate_state_for_checkpoint(state: Dict[str, Any]) -> tuple[bool, List[str]]:
    """
    Валидирует state перед сохранением в checkpoint.
    Дополнительные проверки для критичных полей.
    
    Args:
        state: Словарь состояния для валидации
    
    Returns:
        Tuple (is_valid, errors_list)
    """
    is_valid, errors = validate_state(state)
    
    # Дополнительные проверки для checkpoint
    case_id = state.get("case_id")
    if case_id:
        # Проверка на допустимые символы в case_id (для безопасности)
        if not case_id.replace("-", "").replace("_", "").isalnum():
            errors.append("case_id contains invalid characters")
    
    return len(errors) == 0, errors









