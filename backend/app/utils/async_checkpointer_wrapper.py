"""
Async wrapper for PostgresSaver to enable astream_events support

PostgresSaver doesn't implement async methods required by astream_events,
so we create an async wrapper that uses asyncio to run sync methods.
"""
import asyncio
from typing import Optional, Any, Dict, Tuple
from langgraph.checkpoint.postgres import PostgresSaver
import logging

logger = logging.getLogger(__name__)


class AsyncPostgresSaverWrapper:
    """
    Async wrapper for PostgresSaver to support astream_events
    
    Wraps PostgresSaver and implements async methods (aget_tuple) 
    by running sync methods in executor.
    
    This wrapper allows astream_events to work with PostgresSaver
    by providing async versions of checkpoint methods.
    """
    
    def __init__(self, postgres_saver: PostgresSaver):
        """
        Initialize wrapper with PostgresSaver instance
        
        Args:
            postgres_saver: PostgresSaver instance to wrap
        """
        # Store the wrapped saver
        self._wrapped_saver = postgres_saver
        # Copy all attributes to make wrapper transparent
        # This ensures isinstance checks and attribute access work correctly
        for key, value in postgres_saver.__dict__.items():
            if not key.startswith('_') or key == '_conn':
                setattr(self, key, value)
    
    async def aget_tuple(self, config: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
        """
        Async version of get_tuple
        
        Runs sync get_tuple in executor to avoid blocking event loop
        
        Args:
            config: Configuration dict with thread_id and other params
            
        Returns:
            Tuple from checkpoint or None
        """
        # Get sync method from wrapped saver
        sync_get_tuple = getattr(self._wrapped_saver, 'get_tuple', None)
        if sync_get_tuple is None:
            # If method doesn't exist, raise NotImplementedError to match base behavior
            raise NotImplementedError("get_tuple not available in PostgresSaver")
        
        # Run sync method in executor to avoid blocking event loop
        try:
            loop = asyncio.get_event_loop()
            # Use None for executor to use default ThreadPoolExecutor
            result = await loop.run_in_executor(
                None,  # Use default executor
                sync_get_tuple,
                config
            )
            return result
        except Exception as e:
            logger.error(f"Error in aget_tuple wrapper: {e}", exc_info=True)
            raise
    
    def __getattr__(self, name: str) -> Any:
        """
        Delegate all other attributes and methods to wrapped PostgresSaver
        
        This allows the wrapper to act as a drop-in replacement
        """
        return getattr(self._wrapped_saver, name)


def wrap_postgres_saver_if_needed(checkpointer: Any) -> Any:
    """
    Wrap PostgresSaver with async wrapper if it's PostgresSaver
    
    Args:
        checkpointer: Checkpointer instance (PostgresSaver, MemorySaver, etc.)
        
    Returns:
        Wrapped checkpointer if PostgresSaver, original otherwise
    """
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.checkpoint.memory import MemorySaver
    
    # Only wrap PostgresSaver (MemorySaver already supports async)
    if isinstance(checkpointer, PostgresSaver):
        logger.info("Wrapping PostgresSaver with AsyncPostgresSaverWrapper for astream_events support")
        return AsyncPostgresSaverWrapper(checkpointer)
    
    # Return as-is for MemorySaver and other checkpointers
    return checkpointer

