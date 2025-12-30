"""File System Tools for agents (inspired by DeepAgents)"""
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
import json
import logging
import os

logger = logging.getLogger(__name__)

# Global FileSystemContext instance (will be initialized per case)
_file_system_context: Optional[Any] = None


def initialize_file_system_tools(file_system_context: Any) -> None:
    """Initialize global FileSystemContext instance"""
    global _file_system_context
    _file_system_context = file_system_context
    logger.info("File system tools initialized")


def _ensure_file_system_context(case_id: str = None) -> bool:
    """Ensure FileSystemContext is initialized, create if needed"""
    global _file_system_context
    
    if _file_system_context:
        return True
    
    # Try to create FileSystemContext automatically
    try:
        from app.services.langchain_agents.file_system_context import FileSystemContext
        import os
        
        workspace_base_path = os.getenv("WORKSPACE_BASE_PATH", os.path.join(os.getcwd(), "workspaces"))
        
        # If case_id is provided, use it; otherwise use a default
        if case_id:
            _file_system_context = FileSystemContext(workspace_base_path, case_id)
            logger.info(f"Auto-initialized FileSystemContext for case {case_id}")
            return True
        else:
            # Try to get case_id from state if available
            # This is a fallback - ideally context should be initialized before use
            logger.warning("FileSystemContext not initialized and no case_id provided")
            return False
    except Exception as e:
        logger.warning(f"Failed to auto-initialize FileSystemContext: {e}")
        return False


@tool
def ls_tool(path: str = ".", case_id: str = None) -> str:
    """
    Список файлов в workspace.
    
    Используй этот инструмент для просмотра доступных результатов и файлов.
    
    Args:
        path: Путь относительно workspace (по умолчанию "." - корень)
              Можно указать поддиректорию: "results", "intermediate", "reports"
        case_id: Идентификатор дела (опционально, для автоматической инициализации)
    
    Returns:
        JSON строка со списком файлов или сообщение об ошибке
    """
    global _file_system_context
    
    if not _file_system_context:
        if not _ensure_file_system_context(case_id):
        return json.dumps({
            "error": "File system context not initialized",
                "message": "FileSystemContext not available. Please ensure workspace is initialized."
        })
    
    try:
        # Если path содержит поддиректорию, используем её
        if path in ["results", "intermediate", "reports"]:
            files = _file_system_context.list_files("*", subdirectory=path)
        elif path == "." or path == "":
            # Список всех файлов рекурсивно
            all_files = []
            for subdir in ["results", "intermediate", "reports"]:
                subdir_files = _file_system_context.list_files("*", subdirectory=subdir)
                all_files.extend([f"{subdir}/{f}" for f in subdir_files])
            # Также корневые файлы
            root_files = _file_system_context.list_files("*", subdirectory=None)
            all_files.extend([f for f in root_files if "/" not in f])
            files = all_files
        else:
            # Попытка найти файлы по паттерну
            files = _file_system_context.list_files(path, subdirectory=None)
        
        result = {
            "path": path,
            "files": files,
            "count": len(files)
        }
        
        logger.debug(f"ls_tool: Found {len(files)} files in {path}")
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error in ls_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def read_file_tool(filename: str, case_id: str = None) -> str:
    """
    Читает файл из workspace.
    
    Используй этот инструмент для чтения результатов других агентов или промежуточных данных.
    
    Args:
        filename: Имя файла или путь относительно workspace
                  Примеры: "timeline.json", "results/key_facts.json", "plan.json"
        case_id: Идентификатор дела (опционально, для автоматической инициализации)
    
    Returns:
        Содержимое файла (JSON строка для JSON файлов) или сообщение об ошибке
    """
    global _file_system_context
    
    if not _file_system_context:
        if not _ensure_file_system_context(case_id):
        return json.dumps({
            "error": "File system context not initialized",
                "message": "FileSystemContext not available. Please ensure workspace is initialized."
        })
    
    try:
        # Определяем поддиректорию из пути
        if "/" in filename:
            parts = filename.split("/", 1)
            subdirectory = parts[0]
            filename = parts[1]
        else:
            # Сначала проверяем results, потом intermediate, потом reports
            subdirectory = None
            for subdir in ["results", "intermediate", "reports"]:
                if _file_system_context.file_exists(filename, subdirectory=subdir):
                    subdirectory = subdir
                    break
            # Если не найден, проверяем корень
            if subdirectory is None:
                filepath = os.path.join(_file_system_context.workspace_path, filename)
                if os.path.exists(filepath):
                    subdirectory = ""
                else:
                    return json.dumps({
                        "error": "File not found",
                        "filename": filename,
                        "message": f"File {filename} not found in workspace"
                    })
        
        content = _file_system_context.read_result(
            filename,
            subdirectory=subdirectory if subdirectory else "results"
        )
        
        if content is None:
            return json.dumps({
                "error": "File not found",
                "filename": filename
            })
        
        logger.debug(f"read_file_tool: Read file {filename}")
        return content
    except Exception as e:
        logger.error(f"Error in read_file_tool: {e}")
        return json.dumps({"error": str(e)})


@tool
def write_file_tool(filename: str, content: str, subdirectory: str = "results", case_id: str = None) -> str:
    """
    Записывает результат в файл.
    
    Используй этот инструмент для сохранения результатов работы агента.
    ВСЕГДА сохраняй результаты в файлы, а не только в state.
    
    Args:
        filename: Имя файла (например, "timeline.json", "key_facts.json")
        content: Содержимое файла (строка или JSON строка)
        subdirectory: Поддиректория ("results", "intermediate", "reports")
        case_id: Идентификатор дела (опционально, для автоматической инициализации)
                     По умолчанию "results" для результатов агентов
    
    Returns:
        JSON строка с результатом операции
    """
    global _file_system_context
    
    if not _file_system_context:
        if not _ensure_file_system_context(case_id):
        return json.dumps({
            "error": "File system context not initialized",
                "message": "FileSystemContext not available. Please ensure workspace is initialized."
        })
    
    try:
        # Если content выглядит как JSON, парсим его
        try:
            content_dict = json.loads(content)
            filepath = _file_system_context.write_result(
                filename,
                content_dict,
                subdirectory=subdirectory
            )
        except json.JSONDecodeError:
            # Если не JSON, записываем как текст
            filepath = _file_system_context.write_result(
                filename,
                content,
                subdirectory=subdirectory
            )
        
        result = {
            "success": True,
            "filename": filename,
            "filepath": filepath,
            "subdirectory": subdirectory,
            "message": f"File {filename} written successfully"
        }
        
        logger.info(f"write_file_tool: Wrote file {filename} to {subdirectory}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in write_file_tool: {e}")
        return json.dumps({"error": str(e), "success": False})


@tool
def edit_file_tool(filename: str, old_text: str, new_text: str, subdirectory: str = "results", case_id: str = None) -> str:
    """
    Редактирует существующий файл (замена текста).
    
    Используй этот инструмент для обновления существующих результатов.
    
    Args:
        filename: Имя файла
        old_text: Текст для замены
        new_text: Новый текст
        subdirectory: Поддиректория
        case_id: Идентификатор дела (опционально, для автоматической инициализации)
    
    Returns:
        JSON строка с результатом операции
    """
    global _file_system_context
    
    if not _file_system_context:
        if not _ensure_file_system_context(case_id):
        return json.dumps({
            "error": "File system context not initialized",
                "message": "FileSystemContext not available. Please ensure workspace is initialized."
        })
    
    try:
        success = _file_system_context.edit_file(
            filename,
            old_text,
            new_text,
            subdirectory=subdirectory
        )
        
        if success:
            result = {
                "success": True,
                "filename": filename,
                "message": f"File {filename} edited successfully"
            }
        else:
            result = {
                "success": False,
                "filename": filename,
                "error": "File not found or old_text not found in file"
            }
        
        logger.debug(f"edit_file_tool: Edited file {filename}, success={success}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in edit_file_tool: {e}")
        return json.dumps({"error": str(e), "success": False})


@tool
def write_todos_tool(todos: str, case_id: str = None) -> str:
    """
    Записывает план задач (как DeepAgents write_todos).
    
    Используй этот инструмент для сохранения плана анализа.
    План сохраняется в plan.json в корне workspace.
    
    Args:
        todos: JSON строка с массивом задач или словарем с планом
               Формат: {"goals": [...], "steps": [...], "reasoning": "..."}
               или [{"step_id": "...", "description": "...", ...}, ...]
        case_id: Идентификатор дела (опционально, для автоматической инициализации)
    
    Returns:
        JSON строка с результатом операции
    """
    global _file_system_context
    
    if not _file_system_context:
        if not _ensure_file_system_context(case_id):
        return json.dumps({
            "error": "File system context not initialized",
                "message": "FileSystemContext not available. Please ensure workspace is initialized."
        })
    
    try:
        # Парсим todos как JSON
        try:
            todos_dict = json.loads(todos) if isinstance(todos, str) else todos
        except json.JSONDecodeError:
            return json.dumps({
                "error": "Invalid JSON format",
                "message": "todos must be a valid JSON string"
            })
        
        # Сохраняем в plan.json в корне workspace
        filepath = _file_system_context.write_result(
            "plan.json",
            todos_dict,
            subdirectory=""  # Корень workspace
        )
        
        result = {
            "success": True,
            "filename": "plan.json",
            "filepath": filepath,
            "message": "Plan written successfully"
        }
        
        logger.info("write_todos_tool: Plan written to plan.json")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error in write_todos_tool: {e}")
        return json.dumps({"error": str(e), "success": False})


def get_file_system_tools() -> List:
    """Get all file system tools"""
    return [
        ls_tool,
        read_file_tool,
        write_file_tool,
        edit_file_tool,
        write_todos_tool
    ]

