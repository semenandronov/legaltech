"""Helper functions for context management in agent nodes"""
from typing import Dict, Any, Optional
from app.services.context_manager import ContextManager
import logging

logger = logging.getLogger(__name__)

# Global context manager instance
_context_manager: Optional[ContextManager] = None


def get_context_manager() -> Optional[ContextManager]:
    """Get global context manager instance"""
    global _context_manager
    if _context_manager is None:
        try:
            _context_manager = ContextManager()
            logger.info("✅ Context Manager initialized for agent nodes")
        except Exception as e:
            logger.warning(f"Failed to initialize ContextManager: {e}")
    return _context_manager


def save_agent_context(
    case_id: str,
    agent_name: str,
    result: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
    use_filesystem: bool = True
) -> bool:
    """
    Сохраняет контекст выполнения агента
    
    Args:
        case_id: Case identifier
        agent_name: Name of the agent (timeline, key_facts, etc.)
        result: Agent result dictionary
        metadata: Optional metadata
        
    Returns:
        True if saved successfully
    """
    context_manager = get_context_manager()
    if not context_manager:
        return False
    
    try:
        context = {
            "agent_name": agent_name,
            "result": result,
            "metadata": metadata or {}
        }
        
        # Use filesystem for large results
        if use_filesystem:
            result_size = len(str(result))
            if result_size > 10000:  # More than 10KB
                # Save as analysis result (supports chunking)
                context_manager.save_analysis_result(
                    case_id=case_id,
                    agent_name=agent_name,
                    result=context,
                    chunk_size=1000
                )
                logger.debug(f"Large context saved to filesystem for agent {agent_name} in case {case_id}")
            else:
                # Save as regular context
                context_manager.save_context(
                    case_id=case_id,
                    analysis_type=agent_name,
                    context=context
                )
                logger.debug(f"Saved context for agent {agent_name} in case {case_id}")
        else:
            # Save as regular context
            context_manager.save_context(
                case_id=case_id,
                analysis_type=agent_name,
                context=context
            )
            logger.debug(f"Saved context for agent {agent_name} in case {case_id}")
        
        return True
        
    except Exception as e:
        logger.warning(f"Failed to save context for agent {agent_name}: {e}")
        return False


def load_agent_context(
    case_id: str,
    agent_name: str,
    version: Optional[int] = None,
    use_filesystem: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Загружает контекст выполнения агента
    
    Args:
        case_id: Case identifier
        agent_name: Name of the agent
        version: Optional version number
        use_filesystem: If True, tries to load from filesystem first
        
    Returns:
        Context dictionary or None
    """
    context_manager = get_context_manager()
    if not context_manager:
        return None
    
    try:
        # Try filesystem first if enabled
        if use_filesystem:
            analysis_result = context_manager.load_analysis_result(
                case_id=case_id,
                agent_name=agent_name
            )
            if analysis_result:
                logger.debug(f"Loaded context from filesystem for agent {agent_name} in case {case_id}")
                return analysis_result.get("result") if isinstance(analysis_result, dict) else analysis_result
        
        # Fallback to regular context
        context = context_manager.load_context(
            case_id=case_id,
            analysis_type=agent_name,
            version=version
        )
        
        if context:
            logger.debug(f"Loaded context for agent {agent_name} in case {case_id}")
        
        return context
        
    except Exception as e:
        logger.warning(f"Failed to load context for agent {agent_name}: {e}")
        return None

