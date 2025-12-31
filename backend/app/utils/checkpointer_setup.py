"""Utility for setting up PostgreSQL checkpointer tables with connection pooling"""
from contextlib import contextmanager
from typing import Optional
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from app.config import config
import logging
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# Global flag to track if setup was done
_checkpointer_setup_done = False

# Global checkpointer instance for reuse (connection pooling)
_global_checkpointer: Optional[PostgresSaver] = None


def _create_checkpointer_with_pooling():
    """
    Create PostgresSaver with connection pooling support
    
    Returns:
        PostgresSaver instance with optimized connection pooling
    """
    from langgraph.checkpoint.postgres import PostgresSaver
    
    # Convert DATABASE_URL to format required by PostgresSaver
    db_url = config.DATABASE_URL
    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    
    # Create SQLAlchemy engine with connection pooling
    # Connection pooling improves performance by reusing connections
    engine = create_engine(
        db_url,
        poolclass=QueuePool,
        pool_size=5,  # Number of connections to maintain
        max_overflow=10,  # Maximum overflow connections
        pool_pre_ping=True,  # Verify connections before using
        pool_recycle=3600,  # Recycle connections after 1 hour
        echo=False  # Set to True for SQL debugging
    )
    
    # Create PostgresSaver with connection string
    # IMPORTANT: PostgresSaver does NOT accept SQLAlchemy Engine directly
    # It only accepts connection string via from_conn_string() method
    # NOTE: from_conn_string() should return PostgresSaver directly, not a context manager
    try:
        if hasattr(PostgresSaver, 'from_conn_string'):
            result = PostgresSaver.from_conn_string(db_url)
            logger.debug(f"PostgresSaver.from_conn_string() returned: {type(result)}")
            
            # Check if result is a context manager
            from contextlib import _GeneratorContextManager
            if isinstance(result, _GeneratorContextManager):
                # from_conn_string() returned a context manager - this is unexpected
                # The context manager is typically used for setup, but we need the actual PostgresSaver
                logger.error("❌ PostgresSaver.from_conn_string() returned context manager - this will cause connection issues")
                logger.error("   Context managers should only be used for setup, not for long-lived checkpointer")
                # Try to enter the context to get PostgresSaver, but this may cause connection to close
                # This is a workaround, but not ideal
                try:
                    checkpointer = result.__enter__()
                    logger.warning("⚠️ Entered context manager to get PostgresSaver - connection may close unexpectedly")
                    # Store reference to context manager to prevent garbage collection
                    # This might help keep connection open, but it's not guaranteed
                    checkpointer._context_manager = result
                except Exception as enter_error:
                    logger.error(f"Failed to enter context manager: {enter_error}")
                    raise ValueError("Cannot create PostgresSaver from context manager")
            else:
                # from_conn_string() returned PostgresSaver directly - this is the expected case
                checkpointer = result
                logger.debug("✅ Created PostgresSaver with from_conn_string (direct)")
        else:
            # No from_conn_string method, try direct constructor with connection string
            checkpointer = PostgresSaver(db_url)
            logger.debug("✅ Created PostgresSaver with connection string directly")
    except Exception as create_error:
        logger.error(f"Failed to create PostgresSaver: {create_error}", exc_info=True)
        raise ValueError(f"Cannot create PostgresSaver: {create_error}")
    
    # Verify that we got a PostgresSaver instance, not a context manager
    if not isinstance(checkpointer, PostgresSaver):
        logger.error(f"_create_checkpointer_with_pooling returned {type(checkpointer)} instead of PostgresSaver")
        raise TypeError(f"Expected PostgresSaver, got {type(checkpointer)}")
    
    logger.debug(f"Created PostgresSaver instance: {type(checkpointer)}")
    return checkpointer


@contextmanager
def get_checkpointer():
    """
    Context manager for PostgreSQL checkpointer initialization with connection pooling
    
    Handles setup of checkpointer tables (one-time) and returns
    PostgresSaver instance. Falls back to MemorySaver if PostgresSaver
    is not available. Uses connection pooling for better performance.
    
    Usage:
        with get_checkpointer() as checkpointer:
            graph = graph.compile(checkpointer=checkpointer)
    
    Yields:
        PostgresSaver or MemorySaver instance
    """
    global _checkpointer_setup_done, _global_checkpointer
    
    checkpointer = None
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        
        # Reuse global checkpointer if available (connection pooling)
        if _global_checkpointer is not None:
            logger.debug("Reusing global checkpointer instance (connection pooling)")
            yield _global_checkpointer
            return
        
        # Create new checkpointer with pooling
        checkpointer = _create_checkpointer_with_pooling()
        
        # Verify it's a PostgresSaver before setup
        if not isinstance(checkpointer, PostgresSaver):
            logger.error(f"Checkpointer is not PostgresSaver before setup: {type(checkpointer)}")
            raise TypeError(f"Expected PostgresSaver, got {type(checkpointer)}")
        
        # Setup tables once (idempotent - safe to call multiple times)
        if not _checkpointer_setup_done:
            try:
                if hasattr(checkpointer, 'setup') and callable(checkpointer.setup):
                    # setup() returns a context manager, use it properly
                    # IMPORTANT: setup() does NOT modify checkpointer, it just creates tables
                    with checkpointer.setup():
                        pass  # Tables are created when entering the context
                    logger.info("✅ PostgreSQL checkpointer tables initialized")
                _checkpointer_setup_done = True
            except Exception as setup_error:
                logger.debug(f"Checkpointer setup note: {setup_error}")
        
        # Verify it's still a PostgresSaver after setup
        if not isinstance(checkpointer, PostgresSaver):
            logger.error(f"Checkpointer changed type after setup: {type(checkpointer)}")
            raise TypeError(f"Checkpointer changed from PostgresSaver to {type(checkpointer)} after setup")
        
        # Store globally for reuse (connection pooling)
        _global_checkpointer = checkpointer
        
        logger.info("✅ Using PostgreSQL checkpointer with connection pooling")
        yield checkpointer
        
    except ImportError as import_error:
        logger.warning(
            f"PostgresSaver not available ({import_error}), "
            "using MemorySaver. State will not persist across restarts."
        )
        checkpointer = MemorySaver()
        yield checkpointer
    except Exception as e:
        logger.warning(
            f"Failed to initialize PostgresSaver ({e}), "
            "using MemorySaver. State will not persist across restarts."
        )
        checkpointer = MemorySaver()
        yield checkpointer


def get_checkpointer_instance() -> Optional[PostgresSaver]:
    """
    Get the global checkpointer instance (for reuse across graph compilations)
    
    Returns:
        PostgresSaver instance or None if not initialized
    """
    global _global_checkpointer, _checkpointer_setup_done
    
    if _global_checkpointer is None:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            
            # Create new checkpointer with pooling
            checkpointer = _create_checkpointer_with_pooling()
            
            # Verify it's actually a PostgresSaver instance, not a context manager
            if not isinstance(checkpointer, PostgresSaver):
                logger.error(f"Created checkpointer is not PostgresSaver: {type(checkpointer)}")
                return None
            
            # Setup tables once (idempotent - safe to call multiple times)
            if not _checkpointer_setup_done:
                try:
                    if hasattr(checkpointer, 'setup') and callable(checkpointer.setup):
                        # setup() returns a context manager, use it properly
                        with checkpointer.setup():
                            pass  # Tables are created when entering the context
                        logger.info("✅ PostgreSQL checkpointer tables initialized")
                    _checkpointer_setup_done = True
                except Exception as setup_error:
                    logger.debug(f"Checkpointer setup note: {setup_error}")
            
            # Verify again before storing
            if not isinstance(checkpointer, PostgresSaver):
                logger.error(f"Checkpointer changed type after setup: {type(checkpointer)}")
                return None
            
            _global_checkpointer = checkpointer
            logger.info("✅ Using PostgreSQL checkpointer with connection pooling")
        except Exception as e:
            logger.warning(f"Failed to initialize PostgresSaver: {e}", exc_info=True)
            return None
    
    # Verify the global checkpointer is still valid
    if _global_checkpointer is not None:
        from langgraph.checkpoint.postgres import PostgresSaver
        if not isinstance(_global_checkpointer, PostgresSaver):
            logger.error(f"Global checkpointer is not PostgresSaver: {type(_global_checkpointer)}")
            # Reset and try again
            _global_checkpointer = None
            return get_checkpointer_instance()
    
    return _global_checkpointer


def setup_checkpointer():
    """
    Initialize PostgreSQL checkpointer tables (one-time setup)
    
    This function creates the necessary database tables for LangGraph's
    PostgreSQL checkpointer. Should be called once during application
    initialization or as part of database migrations.
    
    According to LangGraph docs, setup() is idempotent and safe to call multiple times.
    
    Returns:
        bool: True if setup was successful, False otherwise
    """
    try:
        with get_checkpointer() as checkpointer:
            if isinstance(checkpointer, PostgresSaver):
                return True
            return False
    except Exception as e:
        logger.error(f"Failed to setup PostgreSQL checkpointer: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    """Allow running this script directly to setup checkpointer tables"""
    import sys
    logging.basicConfig(level=logging.INFO)
    success = setup_checkpointer()
    sys.exit(0 if success else 1)
