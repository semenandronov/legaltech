"""Utility for setting up PostgreSQL checkpointer tables"""
from langgraph.checkpoint.postgres import PostgresSaver
from app.config import config
import logging

logger = logging.getLogger(__name__)


def setup_checkpointer():
    """
    Initialize PostgreSQL checkpointer tables
    
    This function creates the necessary database tables for LangGraph's
    PostgreSQL checkpointer. Should be called once during application
    initialization or as part of database migrations.
    
    Returns:
        bool: True if setup was successful, False otherwise
    """
    try:
        checkpointer = PostgresSaver.from_conn_string(config.DATABASE_URL)
        checkpointer.setup()
        logger.info("✅ PostgreSQL checkpointer tables created successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to setup PostgreSQL checkpointer: {e}")
        return False


if __name__ == "__main__":
    """Allow running this script directly to setup checkpointer tables"""
    import sys
    logging.basicConfig(level=logging.INFO)
    success = setup_checkpointer()
    sys.exit(0 if success else 1)
