"""
Async wrapper for PostgresSaver to enable astream_events support

PostgresSaver doesn't implement async methods required by astream_events,
so we use monkey-patching to add async methods directly to the instance.
"""
import asyncio
from typing import Optional, Any, Dict, Tuple
from langgraph.checkpoint.postgres import PostgresSaver
import logging

logger = logging.getLogger(__name__)


def _add_aget_tuple_to_instance(postgres_saver: PostgresSaver):
    """
    Add aget_tuple method directly to PostgresSaver instance using monkey-patching
    
    Args:
        postgres_saver: PostgresSaver instance to add the method to
    """
    logger.info(f"Adding aget_tuple to PostgresSaver instance: {type(postgres_saver)}, id: {id(postgres_saver)}")
    
    # Create async method that will be bound to the instance
    # Use closure to capture the postgres_saver instance
    async def aget_tuple_method(config: Dict[str, Any]) -> Optional[Tuple[Any, ...]]:
        """
        Async version of get_tuple
        
        Runs sync get_tuple in executor to avoid blocking event loop
        
        Args:
            config: Configuration dict with thread_id and other params
            
        Returns:
            Tuple from checkpoint or None
        """
        logger.debug(f"aget_tuple called with config: {config}")
        # Get sync method from the captured instance
        sync_get_tuple = getattr(postgres_saver, 'get_tuple', None)
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
            logger.debug(f"aget_tuple completed successfully")
            return result
        except Exception as e:
            logger.error(f"Error in aget_tuple wrapper: {e}", exc_info=True)
            raise
    
    # Bind the async method to the instance using functools.partial or direct assignment
    # For async methods, we need to use a different approach
    # Direct assignment should work for bound methods
    import types
    bound_method = types.MethodType(aget_tuple_method, postgres_saver)
    postgres_saver.aget_tuple = bound_method
    
    # Verify it was added correctly
    has_method = hasattr(postgres_saver, 'aget_tuple')
    method_callable = callable(getattr(postgres_saver, 'aget_tuple', None))
    logger.info(f"✅ aget_tuple method added to PostgresSaver. Has method: {has_method}, callable: {method_callable}, type: {type(getattr(postgres_saver, 'aget_tuple', None))}")


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
        logger.info(f"Checking PostgresSaver for aget_tuple: hasattr={hasattr(checkpointer, 'aget_tuple')}, type={type(checkpointer)}")
        # Check if aget_tuple already exists (might have been added before)
        existing_aget_tuple = getattr(checkpointer, 'aget_tuple', None)
        if not hasattr(checkpointer, 'aget_tuple') or not callable(existing_aget_tuple):
            logger.info("Adding aget_tuple method to PostgresSaver for astream_events support")
            # Use monkey-patching to add aget_tuple directly to the instance
            _add_aget_tuple_to_instance(checkpointer)
            # Verify it was added
            if not hasattr(checkpointer, 'aget_tuple'):
                logger.error("❌ Failed to add aget_tuple to PostgresSaver!")
            else:
                logger.info("✅ Successfully added aget_tuple to PostgresSaver")
        else:
            logger.info(f"PostgresSaver already has aget_tuple method: {type(existing_aget_tuple)}")
    
    # Return as-is for MemorySaver and other checkpointers
    return checkpointer

