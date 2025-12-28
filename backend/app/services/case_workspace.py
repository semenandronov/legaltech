"""Case Workspace Service for managing file-based context storage"""
from typing import Dict, Any, Optional
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Base workspace directory
WORKSPACE_BASE_DIR = os.getenv("WORKSPACE_BASE_DIR", "/tmp/legal_ai_workspace")


class CaseWorkspace:
    """Service for managing case workspace directories and file-based context storage"""
    
    def __init__(self, workspace_base: str = WORKSPACE_BASE_DIR):
        """Initialize case workspace service
        
        Args:
            workspace_base: Base directory for workspace (default: /tmp/legal_ai_workspace)
        """
        self.workspace_base = Path(workspace_base)
        self.workspace_base.mkdir(parents=True, exist_ok=True)
        logger.info(f"✅ Case Workspace initialized at {self.workspace_base}")
    
    def get_case_dir(self, case_id: str) -> Path:
        """Get case-specific directory
        
        Args:
            case_id: Case identifier
            
        Returns:
            Path to case directory
        """
        case_dir = self.workspace_base / "cases" / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        return case_dir
    
    def save_context(
        self,
        case_id: str,
        agent_name: str,
        data: Dict[str, Any],
        suffix: Optional[str] = None
    ) -> str:
        """
        Save context data to file
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            data: Data to save
            suffix: Optional suffix for filename (e.g., "result", "intermediate")
            
        Returns:
            Path to saved file
        """
        try:
            case_dir = self.get_case_dir(case_id)
            agent_dir = case_dir / agent_name
            agent_dir.mkdir(parents=True, exist_ok=True)
            
            # Create filename
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{agent_name}_{timestamp}"
            if suffix:
                filename = f"{filename}_{suffix}"
            filename = f"{filename}.json"
            
            file_path = agent_dir / filename
            
            # Save to JSON
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"Saved context to {file_path} for agent {agent_name} in case {case_id}")
            return str(file_path)
            
        except Exception as e:
            logger.error(f"Error saving context for {agent_name} in case {case_id}: {e}", exc_info=True)
            raise
    
    def load_context(
        self,
        case_id: str,
        agent_name: str,
        latest: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Load context data from file
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            latest: If True, load latest file, otherwise load first found
            
        Returns:
            Loaded data dictionary or None
        """
        try:
            case_dir = self.get_case_dir(case_id)
            agent_dir = case_dir / agent_name
            
            if not agent_dir.exists():
                return None
            
            # Find JSON files
            json_files = list(agent_dir.glob("*.json"))
            if not json_files:
                return None
            
            # Get latest or first file
            if latest:
                file_path = max(json_files, key=lambda p: p.stat().st_mtime)
            else:
                file_path = min(json_files, key=lambda p: p.stat().st_mtime)
            
            # Load JSON
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.debug(f"Loaded context from {file_path} for agent {agent_name} in case {case_id}")
            return data
            
        except Exception as e:
            logger.warning(f"Error loading context for {agent_name} in case {case_id}: {e}")
            return None
    
    def save_large_result(
        self,
        case_id: str,
        agent_name: str,
        result: Any,
        suffix: str = "result"
    ) -> str:
        """
        Save large result to file (for results that shouldn't be in memory)
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            result: Result data (will be JSON-serialized)
            suffix: Suffix for filename
            
        Returns:
            Path to saved file
        """
        try:
            # Convert result to dict if needed
            if not isinstance(result, dict):
                data = {"result": result}
            else:
                data = result
            
            return self.save_context(case_id, agent_name, data, suffix=suffix)
            
        except Exception as e:
            logger.error(f"Error saving large result for {agent_name} in case {case_id}: {e}", exc_info=True)
            raise
    
    def cleanup(
        self,
        case_id: str,
        keep_results: bool = True
    ) -> bool:
        """
        Cleanup workspace for a case (optionally keep results)
        
        Args:
            case_id: Case identifier
            keep_results: If True, keep result files, only cleanup intermediate files
            
        Returns:
            True if cleanup successful
        """
        try:
            case_dir = self.get_case_dir(case_id)
            
            if not keep_results:
                # Remove entire case directory
                import shutil
                if case_dir.exists():
                    shutil.rmtree(case_dir)
                    logger.info(f"Cleaned up workspace for case {case_id}")
                return True
            else:
                # Keep result files, remove intermediate files
                for agent_dir in case_dir.iterdir():
                    if agent_dir.is_dir():
                        for file_path in agent_dir.glob("*_intermediate.json"):
                            file_path.unlink()
                        logger.debug(f"Cleaned up intermediate files for {agent_dir.name} in case {case_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error cleaning up workspace for case {case_id}: {e}", exc_info=True)
            return False
    
    def get_file_reference(
        self,
        case_id: str,
        agent_name: str,
        suffix: str = "result"
    ) -> Optional[str]:
        """
        Get file reference (path) without loading the file
        
        Args:
            case_id: Case identifier
            agent_name: Name of the agent
            suffix: Suffix for filename
            
        Returns:
            File path or None
        """
        try:
            case_dir = self.get_case_dir(case_id)
            agent_dir = case_dir / agent_name
            
            if not agent_dir.exists():
                return None
            
            # Find file with suffix
            pattern = f"*_{suffix}.json"
            files = list(agent_dir.glob(pattern))
            if not files:
                return None
            
            # Get latest file
            file_path = max(files, key=lambda p: p.stat().st_mtime)
            return str(file_path)
            
        except Exception as e:
            logger.warning(f"Error getting file reference for {agent_name} in case {case_id}: {e}")
            return None
    
    def list_case_files(self, case_id: str) -> Dict[str, List[str]]:
        """
        List all files in case workspace
        
        Args:
            case_id: Case identifier
            
        Returns:
            Dictionary mapping agent names to list of file paths
        """
        try:
            case_dir = self.get_case_dir(case_id)
            files_by_agent = {}
            
            if not case_dir.exists():
                return files_by_agent
            
            for agent_dir in case_dir.iterdir():
                if agent_dir.is_dir():
                    agent_name = agent_dir.name
                    files = [str(f) for f in agent_dir.glob("*.json")]
                    files_by_agent[agent_name] = sorted(files)
            
            return files_by_agent
            
        except Exception as e:
            logger.error(f"Error listing files for case {case_id}: {e}", exc_info=True)
            return {}


def get_case_workspace(workspace_base: Optional[str] = None) -> CaseWorkspace:
    """Get case workspace instance"""
    if workspace_base:
        return CaseWorkspace(workspace_base)
    return CaseWorkspace()

