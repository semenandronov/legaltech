"""LangGraph Store integration for long-term memory"""
from typing import Optional, Any
from app.config import config
import logging

logger = logging.getLogger(__name__)

# Global store instance for reuse
_global_store: Optional[Any] = None


def create_store_instance(db_url: Optional[str] = None) -> Optional[Any]:
    """
    Create LangGraph PostgresStore instance for long-term memory
    
    Args:
        db_url: Database URL (optional, uses config.DATABASE_URL if not provided)
        
    Returns:
        PostgresStore instance or None if unavailable
    """
    global _global_store
    
    # Reuse global instance if available
    if _global_store is not None:
        logger.debug("Reusing global store instance")
        return _global_store
    
    db_url = db_url or config.DATABASE_URL
    
    # Remove psycopg driver prefix if present (PostgresStore expects standard postgresql://)
    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    
    try:
        # Try to import PostgresStore from langgraph.graph.store
        try:
            from langgraph.graph.store import PostgresStore
        except ImportError:
            # Fallback: try alternative import path
            try:
                from langgraph.store.postgres import PostgresStore
            except ImportError:
                logger.warning("PostgresStore not available in langgraph. Store functionality disabled.")
                return None
        
        # Create PostgresStore instance
        # PostgresStore uses similar API to PostgresSaver
        try:
            if hasattr(PostgresStore, 'from_conn_string'):
                store = PostgresStore.from_conn_string(db_url)
            elif hasattr(PostgresStore, '__init__'):
                # Direct initialization
                store = PostgresStore(db_url)
            else:
                logger.warning("PostgresStore API not recognized. Store functionality disabled.")
                return None
            
            # Setup tables if needed (similar to PostgresSaver)
            try:
                if hasattr(store, 'setup') and callable(store.setup):
                    # setup() returns a context manager
                    with store.setup():
                        pass  # Tables are created when entering the context
                    logger.info("✅ LangGraph Store tables initialized")
            except Exception as setup_error:
                logger.debug(f"Store setup note: {setup_error}")
            
            # Store globally for reuse
            _global_store = store
            logger.info("✅ LangGraph PostgresStore initialized for long-term memory")
            return store
            
        except Exception as create_error:
            logger.warning(f"Failed to create PostgresStore: {create_error}. Store functionality disabled.")
            return None
            
    except ImportError as import_error:
        logger.warning(f"PostgresStore not available ({import_error}). Store functionality disabled.")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error creating PostgresStore: {e}. Store functionality disabled.")
        return None


def get_store_instance() -> Optional[Any]:
    """
    Get the global store instance (for reuse across graph compilations)
    
    Returns:
        PostgresStore instance or None if not initialized
    """
    global _global_store
    
    if _global_store is None:
        return create_store_instance()
    
    return _global_store


# Helper functions for using Store in agent nodes
def save_to_store(
    store: Optional[Any],
    namespace: str,
    key: str,
    value: dict,
    case_id: Optional[str] = None
) -> bool:
    """
    Save data to Store (helper function for agent nodes)
    
    Args:
        store: Store instance
        namespace: Namespace for grouping (e.g., "case_patterns", "precedents")
        key: Unique key within namespace
        value: Data to save
        case_id: Optional case ID for namespacing
        
    Returns:
        True if saved successfully
    """
    if store is None:
        logger.debug("Store not available, skipping save")
        return False
    
    try:
        # Use case_id in namespace if provided
        full_namespace = f"{namespace}/{case_id}" if case_id else namespace
        
        # PostgresStore API: put(namespace, key, value)
        if hasattr(store, 'put'):
            store.put(full_namespace, key, value)
            logger.debug(f"Saved to store: {full_namespace}/{key}")
            return True
        elif hasattr(store, 'set'):
            store.set(full_namespace, key, value)
            logger.debug(f"Saved to store: {full_namespace}/{key}")
            return True
        else:
            logger.warning("Store does not support put/set operations")
            return False
            
    except Exception as e:
        logger.error(f"Error saving to store {namespace}/{key}: {e}")
        return False


def load_from_store(
    store: Optional[Any],
    namespace: str,
    key: str,
    case_id: Optional[str] = None
) -> Optional[dict]:
    """
    Load data from Store (helper function for agent nodes)
    
    Args:
        store: Store instance
        namespace: Namespace for grouping
        key: Key to load
        case_id: Optional case ID for namespacing
        
    Returns:
        Loaded data or None if not found
    """
    if store is None:
        logger.debug("Store not available, skipping load")
        return None
    
    try:
        # Use case_id in namespace if provided
        full_namespace = f"{namespace}/{case_id}" if case_id else namespace
        
        # PostgresStore API: get(namespace, key)
        if hasattr(store, 'get'):
            value = store.get(full_namespace, key)
            logger.debug(f"Loaded from store: {full_namespace}/{key}")
            return value
        else:
            logger.warning("Store does not support get operations")
            return None
            
    except Exception as e:
        logger.error(f"Error loading from store {namespace}/{key}: {e}")
        return None


def search_in_store(
    store: Optional[Any],
    namespace: str,
    query: Optional[str] = None,
    case_id: Optional[str] = None,
    limit: int = 10
) -> list:
    """
    Search data in Store (helper function for agent nodes)
    
    Args:
        store: Store instance
        namespace: Namespace to search
        query: Optional search query
        case_id: Optional case ID for namespacing
        limit: Maximum number of results
        
    Returns:
        List of matching items
    """
    if store is None:
        logger.debug("Store not available, skipping search")
        return []
    
    try:
        # Use case_id in namespace if provided
        full_namespace = f"{namespace}/{case_id}" if case_id else namespace
        
        # PostgresStore API: list(namespace) or search(namespace, query)
        if hasattr(store, 'list'):
            items = store.list(full_namespace)
            if query:
                # Filter by query if provided
                filtered = [item for item in items if query.lower() in str(item).lower()]
                return filtered[:limit]
            return items[:limit]
        elif hasattr(store, 'search'):
            if query:
                return store.search(full_namespace, query, limit=limit)
            else:
                return store.list(full_namespace)[:limit]
        else:
            logger.warning("Store does not support list/search operations")
            return []
            
    except Exception as e:
        logger.error(f"Error searching in store {namespace}: {e}")
        return []

