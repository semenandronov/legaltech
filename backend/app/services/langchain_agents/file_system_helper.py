"""Helper functions for file system integration in agent nodes"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.file_system_context import FileSystemContext
import os
import logging

logger = logging.getLogger(__name__)


def save_agent_result_to_file(
    state: AnalysisState,
    agent_type: str,
    result_data: Dict[str, Any]
) -> bool:
    """
    Сохраняет результат агента в файл и обновляет state
    
    Args:
        state: Current analysis state
        agent_type: Тип агента (timeline, key_facts, etc.)
        result_data: Результат для сохранения
        
    Returns:
        True если успешно, False если ошибка
    """
    workspace_path = state.get("workspace_path")
    
    if not workspace_path:
        # Workspace не инициализирован - продолжаем без сохранения в файл
        logger.debug(f"Workspace not initialized, skipping file save for {agent_type}")
        return False
    
    try:
        # Получаем case_id для создания FileSystemContext
        case_id = state.get("case_id", "unknown")
        
        # Определяем base_path из workspace_path
        # workspace_path = {base_path}/workspaces/{case_id}
        base_path = os.path.dirname(os.path.dirname(workspace_path))
        
        # Создаем FileSystemContext
        file_system_context = FileSystemContext(base_path, case_id)
        
        # Сохраняем результат в файл
        result_filename = f"{agent_type}.json"
        file_system_context.write_result(
            result_filename,
            result_data,
            subdirectory="results"
        )
        
        # Обновляем workspace_files в state
        workspace_files = list(state.get("workspace_files", []))
        file_path = f"results/{result_filename}"
        if file_path not in workspace_files:
            workspace_files.append(file_path)
            state["workspace_files"] = workspace_files
        
        logger.debug(f"Saved {agent_type} result to {result_filename}")
        return True
        
    except Exception as e:
        logger.warning(f"Failed to save {agent_type} result to file: {e}")
        return False


def get_file_system_context_from_state(state: AnalysisState) -> Optional[FileSystemContext]:
    """
    Создает FileSystemContext из state (если workspace_path доступен)
    
    Args:
        state: Current analysis state
        
    Returns:
        FileSystemContext или None
    """
    workspace_path = state.get("workspace_path")
    
    if not workspace_path:
        return None
    
    try:
        case_id = state.get("case_id", "unknown")
        # Определяем base_path из workspace_path
        base_path = os.path.dirname(os.path.dirname(workspace_path))
        return FileSystemContext(base_path, case_id)
    except Exception as e:
        logger.warning(f"Failed to create FileSystemContext from state: {e}")
        return None


