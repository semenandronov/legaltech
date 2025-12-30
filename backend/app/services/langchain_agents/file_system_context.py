"""File System Context Management for DeepAgents architecture"""
from typing import Dict, Any, List, Optional
import os
import json
import logging
from pathlib import Path
import glob
import shutil

logger = logging.getLogger(__name__)


class FileSystemContext:
    """
    Управление контекстом через файловую систему.
    Промежуточные результаты сохраняются в файлы, а не в state.
    Вдохновлено DeepAgents architecture.
    """
    
    def __init__(self, base_path: str, case_id: str):
        """
        Initialize FileSystemContext
        
        Args:
            base_path: Base path for workspaces (e.g., "./workspaces")
            case_id: Case identifier
        """
        self.case_id = case_id
        self.workspace_path = os.path.join(base_path, "workspaces", case_id)
        
        # Создаем структуру директорий
        os.makedirs(self.workspace_path, exist_ok=True)
        os.makedirs(os.path.join(self.workspace_path, "results"), exist_ok=True)
        os.makedirs(os.path.join(self.workspace_path, "intermediate"), exist_ok=True)
        os.makedirs(os.path.join(self.workspace_path, "reports"), exist_ok=True)
        
        logger.info(f"FileSystemContext initialized: {self.workspace_path}")
    
    def get_workspace_path(self) -> str:
        """Get workspace path"""
        return self.workspace_path
    
    def write_result(self, filename: str, content: str, subdirectory: str = "results") -> str:
        """
        Записывает результат в файл
        
        Args:
            filename: Имя файла (например, "timeline.json")
            content: Содержимое файла (строка)
            subdirectory: Поддиректория ("results", "intermediate", "reports")
            
        Returns:
            Полный путь к файлу
        """
        target_dir = os.path.join(self.workspace_path, subdirectory)
        os.makedirs(target_dir, exist_ok=True)
        
        filepath = os.path.join(target_dir, filename)
        
        try:
            # Если content - словарь или список, сериализуем в JSON
            if isinstance(content, (dict, list)):
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(content)
            
            logger.debug(f"Wrote result to {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Error writing file {filepath}: {e}")
            raise
    
    def read_result(self, filename: str, subdirectory: str = "results") -> Optional[str]:
        """
        Читает файл из workspace
        
        Args:
            filename: Имя файла
            subdirectory: Поддиректория
            
        Returns:
            Содержимое файла или None если файл не найден
        """
        filepath = os.path.join(self.workspace_path, subdirectory, filename)
        
        if not os.path.exists(filepath):
            logger.warning(f"File not found: {filepath}")
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                # Пытаемся прочитать как JSON, если не получается - как текст
                try:
                    content = json.load(f)
                    return json.dumps(content, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    f.seek(0)
                    return f.read()
        except Exception as e:
            logger.error(f"Error reading file {filepath}: {e}")
            return None
    
    def read_result_as_dict(self, filename: str, subdirectory: str = "results") -> Optional[Dict[str, Any]]:
        """
        Читает JSON файл как словарь
        
        Args:
            filename: Имя файла
            subdirectory: Поддиректория
            
        Returns:
            Словарь с данными или None
        """
        filepath = os.path.join(self.workspace_path, subdirectory, filename)
        
        if not os.path.exists(filepath):
            return None
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading JSON file {filepath}: {e}")
            return None
    
    def list_files(self, pattern: str = "*", subdirectory: str = None) -> List[str]:
        """
        Список файлов в workspace
        
        Args:
            pattern: Шаблон поиска (например, "*.json", "timeline.*")
            subdirectory: Поддиректория для поиска (None = весь workspace)
            
        Returns:
            Список путей к файлам (относительно workspace_path)
        """
        if subdirectory:
            search_path = os.path.join(self.workspace_path, subdirectory, pattern)
        else:
            search_path = os.path.join(self.workspace_path, "**", pattern)
        
        files = []
        try:
            for filepath in glob.glob(search_path, recursive=True):
                # Получаем относительный путь от workspace_path
                rel_path = os.path.relpath(filepath, self.workspace_path)
                files.append(rel_path)
        except Exception as e:
            logger.error(f"Error listing files with pattern {pattern}: {e}")
        
        return sorted(files)
    
    def edit_file(self, filename: str, old_text: str, new_text: str, subdirectory: str = "results") -> bool:
        """
        Редактирует файл (замена текста)
        
        Args:
            filename: Имя файла
            old_text: Текст для замены
            new_text: Новый текст
            subdirectory: Поддиректория
            
        Returns:
            True если успешно, False если ошибка
        """
        filepath = os.path.join(self.workspace_path, subdirectory, filename)
        
        if not os.path.exists(filepath):
            logger.warning(f"File not found for editing: {filepath}")
            return False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if old_text not in content:
                logger.warning(f"Old text not found in file {filepath}")
                return False
            
            new_content = content.replace(old_text, new_text)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            logger.debug(f"Edited file {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error editing file {filepath}: {e}")
            return False
    
    def file_exists(self, filename: str, subdirectory: str = "results") -> bool:
        """Проверяет существование файла"""
        filepath = os.path.join(self.workspace_path, subdirectory, filename)
        return os.path.exists(filepath)
    
    def delete_file(self, filename: str, subdirectory: str = "results") -> bool:
        """Удаляет файл"""
        filepath = os.path.join(self.workspace_path, subdirectory, filename)
        
        if not os.path.exists(filepath):
            return False
        
        try:
            os.remove(filepath)
            logger.debug(f"Deleted file {filepath}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file {filepath}: {e}")
            return False
    
    def get_workspace_summary(self) -> Dict[str, Any]:
        """
        Возвращает summary workspace (количество файлов, размер, структура)
        
        Returns:
            Словарь с информацией о workspace
        """
        summary = {
            "workspace_path": self.workspace_path,
            "case_id": self.case_id,
            "directories": {},
            "total_files": 0,
            "total_size_bytes": 0
        }
        
        try:
            for subdir in ["results", "intermediate", "reports"]:
                subdir_path = os.path.join(self.workspace_path, subdir)
                if os.path.exists(subdir_path):
                    files = []
                    dir_size = 0
                    
                    for filename in os.listdir(subdir_path):
                        filepath = os.path.join(subdir_path, filename)
                        if os.path.isfile(filepath):
                            file_size = os.path.getsize(filepath)
                            files.append({
                                "filename": filename,
                                "size_bytes": file_size
                            })
                            dir_size += file_size
                    
                    summary["directories"][subdir] = {
                        "file_count": len(files),
                        "size_bytes": dir_size,
                        "files": files
                    }
                    summary["total_files"] += len(files)
                    summary["total_size_bytes"] += dir_size
            
            # Также проверяем корневые файлы
            root_files = []
            for filename in os.listdir(self.workspace_path):
                filepath = os.path.join(self.workspace_path, filename)
                if os.path.isfile(filepath):
                    file_size = os.path.getsize(filepath)
                    root_files.append({
                        "filename": filename,
                        "size_bytes": file_size
                    })
                    summary["total_files"] += 1
                    summary["total_size_bytes"] += file_size
            
            if root_files:
                summary["directories"]["root"] = {
                    "file_count": len(root_files),
                    "size_bytes": sum(f["size_bytes"] for f in root_files),
                    "files": root_files
                }
        
        except Exception as e:
            logger.error(f"Error generating workspace summary: {e}")
        
        return summary
    
    def cleanup(self, keep_reports: bool = True) -> bool:
        """
        Очищает workspace (удаляет все файлы кроме reports)
        
        Args:
            keep_reports: Если True, сохраняет reports директорию
            
        Returns:
            True если успешно
        """
        try:
            if keep_reports:
                # Удаляем только results и intermediate
                for subdir in ["results", "intermediate"]:
                    subdir_path = os.path.join(self.workspace_path, subdir)
                    if os.path.exists(subdir_path):
                        shutil.rmtree(subdir_path)
                        os.makedirs(subdir_path, exist_ok=True)
                
                # Удаляем корневые файлы кроме reports
                for filename in os.listdir(self.workspace_path):
                    filepath = os.path.join(self.workspace_path, filename)
                    if os.path.isfile(filepath):
                        os.remove(filepath)
            else:
                # Удаляем всё
                if os.path.exists(self.workspace_path):
                    shutil.rmtree(self.workspace_path)
                    os.makedirs(self.workspace_path, exist_ok=True)
                    os.makedirs(os.path.join(self.workspace_path, "results"), exist_ok=True)
                    os.makedirs(os.path.join(self.workspace_path, "intermediate"), exist_ok=True)
                    os.makedirs(os.path.join(self.workspace_path, "reports"), exist_ok=True)
            
            logger.info(f"Workspace cleaned up: {self.workspace_path}")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up workspace: {e}")
            return False


