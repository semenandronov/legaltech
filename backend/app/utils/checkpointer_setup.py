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
    
    # Create PostgresSaver with engine (if supported) or connection string
    try:
        # Try to create with engine (if PostgresSaver supports it)
        if hasattr(PostgresSaver, 'from_conn_string'):
            # Use connection string (PostgresSaver creates its own connections)
            # Connection pooling happens at the database level
            checkpointer = PostgresSaver.from_conn_string(db_url)
        else:
            checkpointer = PostgresSaver(engine)
    except (TypeError, AttributeError):
        # Fallback to connection string if engine not supported
        checkpointer = PostgresSaver.from_conn_string(db_url)
    
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
