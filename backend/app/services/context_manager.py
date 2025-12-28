"""Context Manager for managing analysis context through filesystem (inspired by DeepAgents)"""
from typing import Dict, Any, Optional, List, Iterator
import os
import json
import jsonlines
import logging
from pathlib import Path
from datetime import datetime
import gzip
import shutil

logger = logging.getLogger(__name__)


class ContextManager:
    """Управление контекстом через файловую систему (вдохновлено DeepAgents)"""
    
    def __init__(self, base_path: str = "/tmp/legal_ai_context"):
        """Initialize context manager
        
        Args:
            base_path: Base path for storing context files
        """
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Context Manager initialized with base path: {self.base_path}")
    
    def save_context(
        self,
        case_id: str,
        analysis_type: str,
        context: Dict[str, Any],
        version: Optional[int] = None
    ) -> str:
        """
        Сохраняет контекст в файл
        
        Args:
            case_id: Case identifier
            analysis_type: Type of analysis (timeline, key_facts, etc.)
            context: Context dictionary to save
            version: Optional version number (if None, auto-increments)
            
        Returns:
            Path to saved file
        """
        try:
            # Create case directory
            case_dir = self.base_path / case_id
            case_dir.mkdir(parents=True, exist_ok=True)
            
            # Determine version
            if version is None:
                version = self._get_next_version(case_dir, analysis_type)
            
            # Create file path
            file_path = case_dir / f"{analysis_type}_v{version}.json"
            
            # Add metadata
            context_with_metadata = {
                "case_id": case_id,
                "analysis_type": analysis_type,
                "version": version,
                "created_at": datetime.utcnow().isoformat(),
                "data": context
            }
            
            # Save to file
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(context_with_metadata, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Context saved: {file_path} (version {version})")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving context: {e}", exc_info=True)
            raise
    
    def load_context(
        self,
        case_id: str,
        analysis_type: str,
        version: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Загружает контекст из файла
        
        Args:
            case_id: Case identifier
            analysis_type: Type of analysis
            version: Optional version number (if None, loads latest)
            
        Returns:
            Context dictionary or None if not found
        """
        try:
            case_dir = self.base_path / case_id
            
            if not case_dir.exists():
                logger.debug(f"Case directory not found: {case_dir}")
                return None
            
            # Determine file path
            if version is not None:
                file_path = case_dir / f"{analysis_type}_v{version}.json"
            else:
                # Find latest version
                file_path = self._get_latest_version_file(case_dir, analysis_type)
            
            if not file_path or not file_path.exists():
                logger.debug(f"Context file not found: {file_path}")
                return None
            
            # Load from file
            with open(file_path, 'r', encoding='utf-8') as f:
                context_data = json.load(f)
            
            logger.info(f"Context loaded: {file_path}")
            return context_data.get("data", context_data)
            
        except Exception as e:
            logger.warning(f"Error loading context: {e}")
            return None
    
    def list_contexts(
        self,
        case_id: str,
        analysis_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Списывает доступные контексты
        
        Args:
            case_id: Case identifier
            analysis_type: Optional filter by analysis type
            
        Returns:
            List of context metadata dictionaries
        """
        try:
            case_dir = self.base_path / case_id
            
            if not case_dir.exists():
                return []
            
            contexts = []
            
            # Find all context files
            pattern = f"{analysis_type}_v*.json" if analysis_type else "*_v*.json"
            for file_path in case_dir.glob(pattern):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        context_data = json.load(f)
                    
                    contexts.append({
                        "file_path": str(file_path),
                        "analysis_type": context_data.get("analysis_type"),
                        "version": context_data.get("version"),
                        "created_at": context_data.get("created_at")
                    })
                except Exception as e:
                    logger.warning(f"Error reading context file {file_path}: {e}")
                    continue
            
            # Sort by created_at descending
            contexts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            
            return contexts
            
        except Exception as e:
            logger.error(f"Error listing contexts: {e}", exc_info=True)
            return []
    
    def delete_context(
        self,
        case_id: str,
        analysis_type: str,
        version: Optional[int] = None
    ) -> bool:
        """
        Удаляет контекст
        
        Args:
            case_id: Case identifier
            analysis_type: Type of analysis
            version: Optional version number (if None, deletes all versions)
            
        Returns:
            True if deleted, False otherwise
        """
        try:
            case_dir = self.base_path / case_id
            
            if not case_dir.exists():
                return False
            
            if version is not None:
                # Delete specific version
                file_path = case_dir / f"{analysis_type}_v{version}.json"
                if file_path.exists():
                    file_path.unlink()
                    logger.info(f"Context deleted: {file_path}")
                    return True
            else:
                # Delete all versions
                pattern = f"{analysis_type}_v*.json"
                deleted_count = 0
                for file_path in case_dir.glob(pattern):
                    file_path.unlink()
                    deleted_count += 1
                
                logger.info(f"Deleted {deleted_count} context files for {analysis_type}")
                return deleted_count > 0
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting context: {e}", exc_info=True)
            return False
    
    def _get_next_version(self, case_dir: Path, analysis_type: str) -> int:
        """Получает следующий номер версии"""
        pattern = f"{analysis_type}_v*.json"
        versions = []
        
        for file_path in case_dir.glob(pattern):
            try:
                # Extract version from filename
                filename = file_path.stem  # e.g., "timeline_v3"
                version_str = filename.split("_v")[-1]
                version = int(version_str)
                versions.append(version)
            except (ValueError, IndexError):
                continue
        
        return max(versions) + 1 if versions else 1
    
    def _get_latest_version_file(
        self,
        case_dir: Path,
        analysis_type: str
    ) -> Optional[Path]:
        """Получает файл с последней версией"""
        pattern = f"{analysis_type}_v*.json"
        files = list(case_dir.glob(pattern))
        
        if not files:
            return None
        
        # Sort by version number
        files_with_versions = []
        for file_path in files:
            try:
                filename = file_path.stem
                version_str = filename.split("_v")[-1]
                version = int(version_str)
                files_with_versions.append((version, file_path))
            except (ValueError, IndexError):
                continue
        
        if not files_with_versions:
            return None
        
        # Return file with highest version
        files_with_versions.sort(key=lambda x: x[0], reverse=True)
        return files_with_versions[0][1]
    
    def clear_case_context(self, case_id: str) -> bool:
        """
        Очищает весь контекст для дела
        
        Args:
            case_id: Case identifier
            
        Returns:
            True if cleared, False otherwise
        """
        try:
            case_dir = self.base_path / case_id
            
            if not case_dir.exists():
                return False
            
            # Delete all files in case directory
            for file_path in case_dir.glob("*"):
                if file_path.is_file():
                    file_path.unlink()
                elif file_path.is_dir():
                    import shutil
                    shutil.rmtree(file_path)
            
            # Remove case directory
            case_dir.rmdir()
            
            logger.info(f"Cleared all context for case {case_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error clearing case context: {e}", exc_info=True)
            return False
    
    def save_analysis_result(
        self,
        case_id: str,
        agent_name: str,
        result: Dict[str, Any],
        chunk_size: int = 1000
    ) -> str:
        """
        Сохранить результат анализа на диск
        
        Поддерживает разбиение больших результатов на части для масштабируемости.
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent (timeline, risks, etc.)
            result: Result dictionary to save
            chunk_size: Maximum size of each chunk (for large results)
            
        Returns:
            Path to saved file
        """
        try:
            # Create case directory structure
            case_dir = self.base_path / case_id
            analysis_dir = case_dir / "analysis"
            analysis_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if result is large (needs chunking)
            result_size = len(str(result))
            if result_size > chunk_size * 1000:  # If larger than chunk_size KB
                # Save as JSONL (streaming format)
                file_path = analysis_dir / f"{agent_name}.jsonl"
                self._save_large_result(result, file_path, chunk_size)
                logger.info(f"Large analysis result saved as JSONL: {file_path}")
            else:
                # Save as regular JSON
                file_path = analysis_dir / f"{agent_name}.json"
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "case_id": case_id,
                        "agent_name": agent_name,
                        "created_at": datetime.utcnow().isoformat(),
                        "data": result
                    }, f, ensure_ascii=False, indent=2)
                logger.info(f"Analysis result saved: {file_path}")
            
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving analysis result: {e}", exc_info=True)
            raise
    
    def load_analysis_result(
        self,
        case_id: str,
        agent_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Загрузить результат анализа с диска
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            
        Returns:
            Result dictionary or None if not found
        """
        try:
            case_dir = self.base_path / case_id
            analysis_dir = case_dir / "analysis"
            
            # Try JSON first
            json_path = analysis_dir / f"{agent_name}.json"
            if json_path.exists():
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"Analysis result loaded: {json_path}")
                return data.get("data", data)
            
            # Try JSONL
            jsonl_path = analysis_dir / f"{agent_name}.jsonl"
            if jsonl_path.exists():
                result = self._load_large_result(jsonl_path)
                logger.info(f"Large analysis result loaded: {jsonl_path}")
                return result
            
            logger.debug(f"Analysis result not found for {agent_name} in case {case_id}")
            return None
            
        except Exception as e:
            logger.warning(f"Error loading analysis result: {e}")
            return None
    
    def stream_large_result(
        self,
        case_id: str,
        agent_name: str,
        batch_size: int = 100
    ) -> Iterator[Dict[str, Any]]:
        """
        Стриминг больших результатов по частям
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            batch_size: Number of items per batch
            
        Yields:
            Batches of result data
        """
        try:
            case_dir = self.base_path / case_id
            analysis_dir = case_dir / "analysis"
            jsonl_path = analysis_dir / f"{agent_name}.jsonl"
            
            if not jsonl_path.exists():
                logger.warning(f"JSONL file not found: {jsonl_path}")
                return
            
            batch = []
            with open(jsonl_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        batch.append(item)
                        
                        if len(batch) >= batch_size:
                            yield batch
                            batch = []
                    except json.JSONDecodeError as e:
                        logger.warning(f"Error parsing JSONL line: {e}")
                        continue
                
                # Yield remaining batch
                if batch:
                    yield batch
                    
        except Exception as e:
            logger.error(f"Error streaming large result: {e}", exc_info=True)
    
    def save_intermediate_result(
        self,
        case_id: str,
        result_type: str,
        data: Dict[str, Any]
    ) -> str:
        """
        Сохранить промежуточный результат (для agent_executions, llm_calls)
        
        Args:
            case_id: Case identifier
            result_type: Type of intermediate result (agent_executions, llm_calls)
            data: Data to save
            
        Returns:
            Path to saved file
        """
        try:
            case_dir = self.base_path / case_id
            intermediate_dir = case_dir / "intermediate"
            intermediate_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = intermediate_dir / f"{result_type}.jsonl"
            
            # Append to JSONL file
            with open(file_path, 'a', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.utcnow().isoformat(),
                    "data": data
                }, f, ensure_ascii=False)
                f.write('\n')
            
            logger.debug(f"Intermediate result saved: {file_path}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving intermediate result: {e}", exc_info=True)
            raise
    
    def _save_large_result(
        self,
        result: Dict[str, Any],
        file_path: Path,
        chunk_size: int
    ):
        """Сохраняет большой результат в формате JSONL"""
        # Если результат содержит списки, разбиваем их на части
        if isinstance(result, dict):
            # Сохраняем метаданные отдельно
            metadata = {
                "case_id": result.get("case_id"),
                "agent_name": result.get("agent_name"),
                "created_at": datetime.utcnow().isoformat(),
                "total_items": len(result.get("data", [])) if isinstance(result.get("data"), list) else 1
            }
            
            with open(file_path, 'w', encoding='utf-8') as f:
                # Записываем метаданные как первую строку
                json.dump({"type": "metadata", **metadata}, f, ensure_ascii=False)
                f.write('\n')
                
                # Записываем данные по частям
                data = result.get("data", result)
                if isinstance(data, list):
                    for item in data:
                        json.dump(item, f, ensure_ascii=False)
                        f.write('\n')
                else:
                    json.dump(data, f, ensure_ascii=False)
                    f.write('\n')
        else:
            # Просто сохраняем как есть
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False)
                f.write('\n')
    
    def _load_large_result(self, file_path: Path) -> Dict[str, Any]:
        """Загружает большой результат из JSONL файла"""
        result = {
            "data": []
        }
        
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    item = json.loads(line)
                    if item.get("type") == "metadata":
                        result.update({k: v for k, v in item.items() if k != "type"})
                    else:
                        if "data" not in result:
                            result["data"] = []
                        result["data"].append(item)
                except json.JSONDecodeError:
                    continue
        
        # Если данные не в списке, возвращаем как есть
        if len(result["data"]) == 1 and not isinstance(result.get("data", [None])[0], dict):
            result = result["data"][0] if result["data"] else result
        
        return result
    
    def get_case_structure(self, case_id: str) -> Dict[str, Any]:
        """
        Получить структуру файлов для дела
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary with file structure
        """
        try:
            case_dir = self.base_path / case_id
            
            if not case_dir.exists():
                return {"case_id": case_id, "exists": False}
            
            structure = {
                "case_id": case_id,
                "exists": True,
                "base_path": str(case_dir),
                "analysis": {},
                "intermediate": {},
                "context": {}
            }
            
            # Analysis results
            analysis_dir = case_dir / "analysis"
            if analysis_dir.exists():
                for file_path in analysis_dir.glob("*.json"):
                    agent_name = file_path.stem
                    file_size = file_path.stat().st_size
                    structure["analysis"][agent_name] = {
                        "path": str(file_path),
                        "size_bytes": file_size,
                        "format": "json"
                    }
                for file_path in analysis_dir.glob("*.jsonl"):
                    agent_name = file_path.stem
                    file_size = file_path.stat().st_size
                    structure["analysis"][agent_name] = {
                        "path": str(file_path),
                        "size_bytes": file_size,
                        "format": "jsonl"
                    }
            
            # Intermediate results
            intermediate_dir = case_dir / "intermediate"
            if intermediate_dir.exists():
                for file_path in intermediate_dir.glob("*.jsonl"):
                    result_type = file_path.stem
                    file_size = file_path.stat().st_size
                    structure["intermediate"][result_type] = {
                        "path": str(file_path),
                        "size_bytes": file_size
                    }
            
            # Context files
            for file_path in case_dir.glob("*_v*.json"):
                analysis_type = file_path.stem.split("_v")[0]
                if analysis_type not in structure["context"]:
                    structure["context"][analysis_type] = []
                structure["context"][analysis_type].append({
                    "path": str(file_path),
                    "version": int(file_path.stem.split("_v")[-1])
                })
            
            return structure
            
        except Exception as e:
            logger.error(f"Error getting case structure: {e}", exc_info=True)
            return {"case_id": case_id, "error": str(e)}

