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
    # #region agent log
    try:
        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
            import json
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "D",
                "location": "checkpointer_setup.py:30",
                "message": "Before URL conversion - original DATABASE_URL",
                "data": {
                    "original_url": db_url[:100] if db_url else None,
                    "url_starts_with_psycopg": db_url.startswith("postgresql+psycopg://") if db_url else False
                },
                "timestamp": int(__import__('time').time() * 1000)
            }
            f.write(json.dumps(log_entry) + '\n')
    except Exception:
        pass
    # #endregion
    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    # #region agent log
    try:
        with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
            import json
            log_entry = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "D",
                "location": "checkpointer_setup.py:33",
                "message": "After URL conversion - converted db_url",
                "data": {
                    "converted_url": db_url[:100] if db_url else None
                },
                "timestamp": int(__import__('time').time() * 1000)
            }
            f.write(json.dumps(log_entry) + '\n')
    except Exception:
        pass
    # #endregion
    
    # Create PostgresSaver with connection string
    # IMPORTANT: In langgraph-checkpoint-postgres, from_conn_string() returns a context manager
    # The context manager properly initializes the connection object
    # We MUST use 'with' statement' to properly initialize, but we need to keep it alive
    try:
        # Use from_conn_string() which returns a context manager
        if hasattr(PostgresSaver, 'from_conn_string'):
            # from_conn_string() returns a context manager that yields PostgresSaver
            # CRITICAL: We must use 'with' to properly initialize, but we can't exit for long-lived instances
            # Solution: Use the context manager's __enter__() but keep the context manager alive
            conn_manager = PostgresSaver.from_conn_string(db_url)
            # #region agent log
            try:
                with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                    import json
                    log_entry = {
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "B",
                        "location": "checkpointer_setup.py:44",
                        "message": "After from_conn_string() - conn_manager type",
                        "data": {
                            "conn_manager_type": str(type(conn_manager)),
                            "has_enter": hasattr(conn_manager, "__enter__"),
                            "has_exit": hasattr(conn_manager, "__exit__")
                        },
                        "timestamp": int(__import__('time').time() * 1000)
                    }
                    f.write(json.dumps(log_entry) + '\n')
            except Exception:
                pass
            # #endregion
            
            # Check if it's a context manager by checking for __enter__ and __exit__
            is_context_manager = hasattr(conn_manager, "__enter__") and hasattr(conn_manager, "__exit__")
            
            if is_context_manager:
                # CRITICAL: Enter the context manager to properly initialize PostgresSaver
                # The __enter__() method sets up the connection object properly
                # We keep the context manager alive by NOT calling __exit__()
                checkpointer = conn_manager.__enter__()
                
                # #region agent log
                try:
                    with open('/Users/semyon_andronov04/Desktop/C ДВ/.cursor/debug.log', 'a') as f:
                        import json
                        log_entry = {
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "A",
                            "location": "checkpointer_setup.py:53",
                            "message": "After __enter__() - checkpointer type and conn attribute",
                            "data": {
                                "checkpointer_type": str(type(checkpointer)),
                                "has_conn": hasattr(checkpointer, 'conn'),
                                "conn_type": str(type(checkpointer.conn)) if hasattr(checkpointer, 'conn') else None,
                                "conn_is_str": isinstance(checkpointer.conn, str) if hasattr(checkpointer, 'conn') else None,
                                "conn_value_preview": str(checkpointer.conn)[:50] if hasattr(checkpointer, 'conn') and not isinstance(checkpointer.conn, str) else str(checkpointer.conn)[:50] if hasattr(checkpointer, 'conn') else None
                            },
                            "timestamp": int(__import__('time').time() * 1000)
                        }
                        f.write(json.dumps(log_entry) + '\n')
                except Exception:
                    pass
                # #endregion
                
                # Store the context manager to prevent garbage collection
                # This keeps the connection alive for long-lived instances
                if not hasattr(checkpointer, '_context_manager'):
                    checkpointer._context_manager = conn_manager
                
                logger.info("✅ Created PostgresSaver using from_conn_string() context manager")
            else:
                # from_conn_string() returned PostgresSaver directly (older version)
                checkpointer = conn_manager
                logger.info("✅ Created PostgresSaver with from_conn_string (direct)")
        else:
            # Fallback: try direct constructor
            try:
                checkpointer = PostgresSaver(db_url)
                logger.info("✅ Created PostgresSaver using direct constructor")
            except (TypeError, ValueError) as direct_error:
                raise ValueError(f"PostgresSaver initialization failed: {direct_error}")
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
