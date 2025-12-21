"""Utility for setting up PostgreSQL checkpointer tables"""
from contextlib import contextmanager
from typing import Optional
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.memory import MemorySaver
from app.config import config
import logging

logger = logging.getLogger(__name__)

# Global flag to track if setup was done
_checkpointer_setup_done = False


@contextmanager
def get_checkpointer():
    """
    Context manager for PostgreSQL checkpointer initialization
    
    Handles setup of checkpointer tables (one-time) and returns
    PostgresSaver instance. Falls back to MemorySaver if PostgresSaver
    is not available.
    
    Usage:
        with get_checkpointer() as checkpointer:
            graph = graph.compile(checkpointer=checkpointer)
    
    Yields:
        PostgresSaver or MemorySaver instance
    """
    global _checkpointer_setup_done
    
    checkpointer = None
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        
        # Convert DATABASE_URL to format required by PostgresSaver
        # PostgresSaver expects postgresql:// format
        db_url = config.DATABASE_URL
        if db_url.startswith("postgresql+psycopg://"):
            db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
        
        # Create PostgresSaver instance
        checkpointer = PostgresSaver.from_conn_string(db_url)
        
        # Setup tables once (idempotent - safe to call multiple times)
        if not _checkpointer_setup_done:
            try:
                if hasattr(checkpointer, 'setup') and callable(checkpointer.setup):
                    checkpointer.setup()
                    logger.info("✅ PostgreSQL checkpointer tables initialized")
                _checkpointer_setup_done = True
            except Exception as setup_error:
                logger.debug(f"Checkpointer setup note: {setup_error}")
        
        logger.info("✅ Using PostgreSQL checkpointer for state persistence")
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
