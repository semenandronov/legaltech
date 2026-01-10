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
    
    # Bind the async method to the instance
    # For async methods, we need to assign directly (not using MethodType which doesn't work well with async)
    # Direct assignment creates a bound method automatically
    postgres_saver.aget_tuple = aget_tuple_method
    
    # Verify it was added correctly
    has_method = hasattr(postgres_saver, 'aget_tuple')
    method_callable = callable(getattr(postgres_saver, 'aget_tuple', None))
    logger.info(f"✅ aget_tuple method added to PostgresSaver. Has method: {has_method}, callable: {method_callable}, type: {type(getattr(postgres_saver, 'aget_tuple', None))}")


def _add_aput_to_instance(postgres_saver: PostgresSaver):
    """
    Add aput method directly to PostgresSaver instance using monkey-patching
    
    Args:
        postgres_saver: PostgresSaver instance to add the method to
    """
    logger.info(f"Adding aput to PostgresSaver instance: {type(postgres_saver)}, id: {id(postgres_saver)}")
    
    # Create async method that will be bound to the instance
    # Use closure to capture the postgres_saver instance
    async def aput_method(config: Dict[str, Any], checkpoint: Any, metadata: Dict[str, Any], new_versions: Dict[str, Any]) -> None:
        """
        Async version of put
        
        Runs sync put in executor to avoid blocking event loop
        
        Args:
            config: Configuration dict with thread_id and other params
            checkpoint: Checkpoint data to save
            metadata: Metadata dict
            new_versions: New versions dict
        """
        logger.debug(f"aput called with config: {config}")
        # Get sync method from the captured instance
        sync_put = getattr(postgres_saver, 'put', None)
        if sync_put is None:
            # If method doesn't exist, raise NotImplementedError to match base behavior
            raise NotImplementedError("put not available in PostgresSaver")
        
        # Run sync method in executor to avoid blocking event loop
        try:
            loop = asyncio.get_event_loop()
            # Use None for executor to use default ThreadPoolExecutor
            await loop.run_in_executor(
                None,  # Use default executor
                sync_put,
                config,
                checkpoint,
                metadata,
                new_versions
            )
            logger.debug(f"aput completed successfully")
        except Exception as e:
            logger.error(f"Error in aput wrapper: {e}", exc_info=True)
            raise
    
    # Bind the async method to the instance
    # For async methods, we need to assign directly (not using MethodType which doesn't work well with async)
    # Direct assignment creates a bound method automatically
    postgres_saver.aput = aput_method
    
    # Verify it was added correctly
    has_method = hasattr(postgres_saver, 'aput')
    method_callable = callable(getattr(postgres_saver, 'aput', None))
    logger.info(f"✅ aput method added to PostgresSaver. Has method: {has_method}, callable: {method_callable}, type: {type(getattr(postgres_saver, 'aput', None))}")


def _add_aput_writes_to_instance(postgres_saver: PostgresSaver):
    """
    Add aput_writes method directly to PostgresSaver instance using monkey-patching
    
    Args:
        postgres_saver: PostgresSaver instance to add the method to
    """
    logger.info(f"Adding aput_writes to PostgresSaver instance: {type(postgres_saver)}, id: {id(postgres_saver)}")
    
    # Create async method that will be bound to the instance
    # Use closure to capture the postgres_saver instance
    async def aput_writes_method(config: Dict[str, Any], writes: Any) -> None:
        """
        Async version of put_writes for batch checkpoint writes
        
        Runs sync put_writes in executor to avoid blocking event loop
        
        Args:
            config: Configuration dict with thread_id and other params
            writes: Write records or write data (structure depends on LangGraph version)
        """
        logger.debug(f"aput_writes called with config: {config}, writes type: {type(writes)}")
        
        # Get sync put_writes method
        sync_put_writes = getattr(postgres_saver, 'put_writes', None)
        
        if sync_put_writes is None:
            # If put_writes doesn't exist, this version of PostgresSaver doesn't support it
            # Raise NotImplementedError to match base class behavior
            raise NotImplementedError("put_writes not available in this version of PostgresSaver")
        
        # Run sync put_writes in executor to avoid blocking event loop
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,  # Use default executor
                sync_put_writes,
                config,
                writes
            )
            logger.debug(f"aput_writes completed successfully")
        except Exception as e:
            logger.error(f"Error in aput_writes wrapper: {e}", exc_info=True)
            raise
    
    # Bind the async method to the instance
    postgres_saver.aput_writes = aput_writes_method
    
    # Verify it was added correctly
    has_method = hasattr(postgres_saver, 'aput_writes')
    method_callable = callable(getattr(postgres_saver, 'aput_writes', None))
    logger.info(f"✅ aput_writes method added to PostgresSaver. Has method: {has_method}, callable: {method_callable}, type: {type(getattr(postgres_saver, 'aput_writes', None))}")


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
        # ALWAYS patch aget_tuple, aput, and aput_writes for PostgresSaver, even if they exist in base class
        # Base class has these methods that raise NotImplementedError, so we must override them
        logger.info("Patching aget_tuple, aput, and aput_writes for PostgresSaver to enable astream_events support")
        _add_aget_tuple_to_instance(checkpointer)
        _add_aput_to_instance(checkpointer)
        _add_aput_writes_to_instance(checkpointer)
    
    # Return as-is for MemorySaver and other checkpointers
    return checkpointer

