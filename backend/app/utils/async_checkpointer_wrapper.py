"""
Async wrapper for PostgresSaver to enable astream_events support

PostgresSaver doesn't implement async methods required by astream_events,
so we use monkey-patching to add async methods directly to the instance.
"""
import asyncio
from functools import partial
from typing import Optional, Any, Dict, Tuple
from langgraph.checkpoint.postgres import PostgresSaver
import logging

logger = logging.getLogger(__name__)


def _is_connection_error(error: Exception) -> bool:
    """
    Determine if an exception is a connection/SSL error that can be retried
    
    Args:
        error: Exception to check
        
    Returns:
        True if this is a retryable connection error, False otherwise
    """
    error_msg = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Check error message for connection-related keywords
    connection_keywords = [
        "ssl connection has been closed",
        "connection has been closed",
        "consuming input failed",
        "connection reset",
        "connection refused",
        "connection timeout",
        "server closed the connection",
        "broken pipe",
        "network",
        "ssl"
    ]
    
    # Check error type
    connection_error_types = [
        "operationalerror",
        "interfaceerror",
        "connectionerror",
        "connectionexception"
    ]
    
    # Check if it's a connection error by message
    if any(keyword in error_msg for keyword in connection_keywords):
        return True
    
    # Check if it's a connection error by type
    if any(error_type in err_type for err_type in connection_error_types):
        return True
    
    # Try to import psycopg/asyncpg exceptions and check
    try:
        import psycopg
        if isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError)):
            return True
    except ImportError:
        pass
    
    try:
        import asyncpg
        if isinstance(error, (asyncpg.exceptions.PostgresConnectionError, asyncpg.exceptions.InterfaceError)):
            return True
    except ImportError:
        pass
    
    return False


async def _retry_on_connection_error(
    func,
    max_retries: int = 3,
    initial_delay: float = 0.5,
    max_delay: float = 5.0,
    backoff_factor: float = 2.0
):
    """
    Retry a function on connection errors with exponential backoff
    
    Args:
        func: Async function to execute
        max_retries: Maximum number of retries
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for exponential backoff
        
    Returns:
        Result of func()
        
    Raises:
        Last exception if all retries are exhausted
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except Exception as e:
            last_exception = e
            
            # Only retry connection errors
            if not _is_connection_error(e):
                logger.debug(f"Non-connection error, not retrying: {type(e).__name__}: {e}")
                raise
            
            # If this was the last attempt, raise
            if attempt >= max_retries:
                logger.error(f"Connection error after {max_retries + 1} attempts: {type(e).__name__}: {e}")
                raise
            
            # Calculate delay with exponential backoff
            delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
            logger.warning(
                f"Connection error (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying after {delay:.2f}s: {type(e).__name__}: {e}"
            )
            await asyncio.sleep(delay)
    
    # Should never reach here, but just in case
    if last_exception:
        raise last_exception


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
        # Use retry logic for connection errors
        async def _execute():
            loop = asyncio.get_event_loop()
            # Use None for executor to use default ThreadPoolExecutor
            return await loop.run_in_executor(
                None,  # Use default executor
                sync_get_tuple,
                config
            )
        
        try:
            result = await _retry_on_connection_error(_execute, max_retries=3)
            logger.debug(f"aget_tuple completed successfully")
            return result
        except Exception as e:
            logger.error(f"Error in aget_tuple wrapper after retries: {e}", exc_info=True)
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
        # Use retry logic for connection errors
        async def _execute():
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
        
        try:
            await _retry_on_connection_error(_execute, max_retries=3)
            logger.debug(f"aput completed successfully")
        except Exception as e:
            logger.error(f"Error in aput wrapper after retries: {e}", exc_info=True)
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
    async def aput_writes_method(*args: Any, **kwargs: Any) -> None:
        """
        Async version of put_writes for batch checkpoint writes
        
        Runs sync put_writes in executor to avoid blocking event loop
        
        LangGraph calls this with (config, writes, task_id) as positional arguments.
        The sync put_writes signature is: put_writes(config, writes, task_id)
        """
        # LangGraph passes (config, writes, task_id) to aput_writes
        # The sync put_writes signature is: put_writes(config, writes, task_id)
        if len(args) != 3:
            raise TypeError(f"aput_writes expected 3 arguments (config, writes, task_id), got {len(args)}")
        
        config = args[0]
        writes = args[1]
        task_id = args[2]
        
        logger.debug(f"aput_writes called with config type: {type(config)}, writes type: {type(writes)}, task_id: {task_id}")
        
        # Get sync put_writes method
        sync_put_writes = getattr(postgres_saver, 'put_writes', None)
        
        if sync_put_writes is None:
            # If put_writes doesn't exist, this version of PostgresSaver doesn't support it
            # Raise NotImplementedError to match base class behavior
            raise NotImplementedError("put_writes not available in this version of PostgresSaver")
        
        # Run sync put_writes in executor to avoid blocking event loop
        # Use functools.partial to properly bind arguments for the executor
        # Use retry logic for connection errors
        async def _execute():
            loop = asyncio.get_event_loop()
            # Use partial to bind arguments to the sync method
            # sync_put_writes is a bound method, so partial will bind (config, writes, task_id) to it
            bound_put_writes = partial(sync_put_writes, config, writes, task_id)
            await loop.run_in_executor(None, bound_put_writes)
        
        try:
            await _retry_on_connection_error(_execute, max_retries=3)
            logger.debug(f"aput_writes completed successfully")
        except Exception as e:
            logger.error(f"Error in aput_writes wrapper after retries: {e}", exc_info=True)
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

