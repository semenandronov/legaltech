"""
LangGraph Store Integration для долгосрочной памяти.

Предоставляет интеграцию с LangGraph Store API для использования
в графах через compile(store=...).

# ИСПОЛЬЗОВАНИЕ
```python
from app.services.langchain_agents.store_integration import get_store_instance

# В create_*_graph функциях:
store = get_store_instance()
compiled = graph.compile(
    checkpointer=checkpointer,
    store=store,  # LangGraph Store для долгосрочной памяти
    **compile_kwargs
)

# В узлах графа - доступ через config:
def my_node(state: MyState, config: dict) -> MyState:
    store = config.get("store")
    if store:
        # Получение данных
        item = store.get(("memory", user_id), "user_profile")
        # Сохранение данных
        store.put(("memory", user_id), "user_profile", {"preferences": {...}})
```

# АРХИТЕКТУРА
- PostgresStore для production (персистентность)
- InMemoryStore для development/testing
- Connection pooling через DATABASE_URL
- Namespace-based организация данных
"""
from typing import Optional, Any, Dict
from app.config import config
import logging

logger = logging.getLogger(__name__)

# Global store instance for reuse (connection pooling)
_global_store: Optional[Any] = None
_store_setup_done: bool = False


def _build_semantic_index_config() -> Optional[Dict[str, Any]]:
    """
    Build index config for PostgresStore semantic search.
    Uses Yandex embeddings when available.
    """
    if not getattr(config, "GLOBAL_MEMORY_SEMANTIC_ENABLED", True):
        return None
    try:
        from app.services.yandex_embeddings import YandexEmbeddings

        emb = YandexEmbeddings()
        if not emb.is_available():
            logger.warning("Semantic memory index disabled: embeddings unavailable")
            return None

        # Compatibility-first shape used by LangGraph stores:
        # - embed: callable for texts -> vectors
        # - dims: vector dimension
        return {
            "embed": emb.embed_documents,
            "dims": 256,
        }
    except Exception as ex:
        logger.warning("Failed to initialize semantic memory index config: %s", ex)
        return None


def _create_postgres_store():
    """
    Create PostgresStore with connection pooling support.
    
    Returns:
        PostgresStore instance or None if not available
    """
    try:
        # Try to import PostgresStore from langgraph
        from langgraph.store.postgres import PostgresStore
    except ImportError:
        logger.warning(
            "langgraph.store.postgres.PostgresStore not available. "
            "Make sure langgraph >= 0.2.0 is installed."
        )
        return None
    
    # Convert DATABASE_URL to format required by PostgresStore
    db_url = config.DATABASE_URL
    if db_url.startswith("postgresql+psycopg://"):
        db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    elif db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql://", 1)
    
    try:
        # PostgresStore использует asyncpg для connection pooling
        import os
        pool_max_size = getattr(config, 'LANGGRAPH_POSTGRES_POOL_MAX_SIZE', 20)
        if "ASYNCPG_POOL_MAX_SIZE" not in os.environ:
            os.environ["ASYNCPG_POOL_MAX_SIZE"] = str(pool_max_size)
        
        # Create PostgresStore
        # Check for from_conn_string method (newer API)
        semantic_index = _build_semantic_index_config()
        if hasattr(PostgresStore, 'from_conn_string'):
            # Try semantic index first; fallback to plain store if signature differs.
            try:
                if semantic_index:
                    conn_manager = PostgresStore.from_conn_string(db_url, index=semantic_index)
                else:
                    conn_manager = PostgresStore.from_conn_string(db_url)
            except TypeError:
                conn_manager = PostgresStore.from_conn_string(db_url)
            
            # Check if it's a context manager
            is_context_manager = hasattr(conn_manager, "__enter__") and hasattr(conn_manager, "__exit__")
            
            if is_context_manager:
                # Enter context manager to properly initialize
                store = conn_manager.__enter__()
                # Store context manager to prevent garbage collection
                if not hasattr(store, '_context_manager'):
                    store._context_manager = conn_manager
                logger.info("✅ Created PostgresStore using from_conn_string() context manager")
            else:
                store = conn_manager
                logger.info("✅ Created PostgresStore with from_conn_string (direct)")
        else:
            # Fallback: try direct constructor
            try:
                if semantic_index:
                    store = PostgresStore(db_url, index=semantic_index)
                else:
                    store = PostgresStore(db_url)
            except TypeError:
                store = PostgresStore(db_url)
            logger.info("✅ Created PostgresStore using direct constructor")
        
        return store
        
    except Exception as e:
        logger.error(f"Failed to create PostgresStore: {e}", exc_info=True)
        return None


def _create_memory_store():
    """
    Create InMemoryStore as fallback.
    
    Returns:
        InMemoryStore instance or None if not available
    """
    try:
        from langgraph.store.memory import InMemoryStore
        store = InMemoryStore()
        logger.info("✅ Created InMemoryStore (fallback)")
        return store
    except ImportError:
        logger.warning("langgraph.store.memory.InMemoryStore not available")
        return None


def get_store_instance() -> Optional[Any]:
    """
    Get the global LangGraph Store instance.
    
    Attempts to create PostgresStore for production use.
    Falls back to InMemoryStore if PostgresStore is not available.
    
    Returns:
        Store instance (PostgresStore or InMemoryStore) or None
        
    Usage:
        store = get_store_instance()
        compiled = graph.compile(checkpointer=checkpointer, store=store)
    """
    global _global_store, _store_setup_done
    
    if _global_store is not None:
        logger.debug("Reusing global store instance (connection pooling)")
        return _global_store
    
    # Try PostgresStore first (production)
    store = _create_postgres_store()
    
    if store is None:
        # Fallback to InMemoryStore (development/testing)
        store = _create_memory_store()
    
    if store is not None:
        # Setup tables if needed
        if not _store_setup_done:
            try:
                if hasattr(store, 'setup') and callable(store.setup):
                    # setup() may return a context manager
                    setup_result = store.setup()
                    if hasattr(setup_result, "__enter__"):
                        with setup_result:
                            pass
                    logger.info("✅ LangGraph Store tables initialized")
                _store_setup_done = True
            except Exception as setup_error:
                logger.debug(f"Store setup note: {setup_error}")
                _store_setup_done = True  # Don't retry
        
        _global_store = store
        logger.info(f"✅ LangGraph Store initialized: {type(store).__name__}")
    else:
        logger.warning("⚠️ LangGraph Store not available - long-term memory disabled")
    
    return _global_store


def reset_store_instance():
    """
    Reset the global store instance.
    
    Useful for testing or when database connection needs to be refreshed.
    """
    global _global_store, _store_setup_done
    
    if _global_store is not None:
        # Cleanup context manager if present
        if hasattr(_global_store, '_context_manager'):
            try:
                _global_store._context_manager.__exit__(None, None, None)
            except Exception:
                pass
    
    _global_store = None
    _store_setup_done = False
    logger.info("LangGraph Store instance reset")


def setup_store():
    """
    Initialize LangGraph Store tables (one-time setup).
    
    This function creates the necessary database tables for LangGraph Store.
    Should be called once during application initialization.
    
    Returns:
        bool: True if setup was successful, False otherwise
    """
    try:
        store = get_store_instance()
        return store is not None
    except Exception as e:
        logger.error(f"Failed to setup LangGraph Store: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    """Allow running this script directly to setup store tables"""
    import sys
    logging.basicConfig(level=logging.INFO)
    success = setup_store()
    sys.exit(0 if success else 1)

