"""LangGraph Store Service for long-term memory"""
from typing import Dict, List, Optional, Any
from app.services.langchain_agents.store_integration import get_store_instance
from sqlalchemy.orm import Session
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class LangGraphStoreService:
    """
    Сервис для работы с LangGraph Store (долгосрочная память)
    
    Использует PostgreSQL-backed store для production
    """
    
    def __init__(self, db: Session):
        """
        Инициализация LangGraph Store Service
        
        Args:
            db: Database session
        """
        self.db = db
        self.store = get_store_instance()
        if self.store:
            logger.info("✅ LangGraphStoreService initialized with PostgresStore")
        else:
            logger.warning("LangGraphStoreService: Store not available, using fallback")
    
    async def put(
        self,
        namespace: str,
        key: str,
        value: Any,
        metadata: Optional[Dict] = None
    ):
        """
        Сохранить значение в store
        
        Args:
            namespace: Namespace (например, case_id)
            key: Ключ
            value: Значение
            metadata: Метаданные
        """
        if not self.store:
            logger.debug("Store not available, skipping put")
            return
        
        try:
            # Преобразуем value в JSON-совместимый формат
            if isinstance(value, dict):
                value_json = json.dumps(value, ensure_ascii=False)
            else:
                value_json = str(value)
            
            # Сохраняем в store
            if hasattr(self.store, 'put'):
                self.store.put(namespace, key, value_json, metadata)
            elif hasattr(self.store, 'set'):
                self.store.set(namespace, key, value_json, metadata)
            else:
                logger.warning("Store does not support put/set operations")
                return
            
            logger.debug(f"Stored in LangGraph Store: {namespace}/{key}")
        except Exception as e:
            logger.error(f"Error storing in LangGraph Store: {e}")
    
    async def get(
        self,
        namespace: str,
        key: str
    ) -> Optional[Any]:
        """
        Получить значение из store
        
        Args:
            namespace: Namespace
            key: Ключ
        
        Returns:
            Значение или None
        """
        if not self.store:
            logger.debug("Store not available, skipping get")
            return None
        
        try:
            if hasattr(self.store, 'get'):
                value = self.store.get(namespace, key)
            elif hasattr(self.store, 'aget'):
                value = await self.store.aget(namespace, key)
            else:
                logger.warning("Store does not support get operations")
                return None
            
            if value:
                # Пробуем распарсить JSON
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        except Exception as e:
            logger.error(f"Error getting from LangGraph Store: {e}")
            return None
    
    async def list(
        self,
        namespace: str,
        limit: Optional[int] = None
    ) -> List[str]:
        """
        Список ключей в namespace
        
        Args:
            namespace: Namespace
            limit: Максимум результатов
        
        Returns:
            Список ключей
        """
        if not self.store:
            logger.debug("Store not available, skipping list")
            return []
        
        try:
            if hasattr(self.store, 'list'):
                keys = self.store.list(namespace, limit=limit)
            elif hasattr(self.store, 'alist'):
                keys = await self.store.alist(namespace, limit=limit)
            else:
                logger.warning("Store does not support list operations")
                return []
            
            return keys if keys else []
        except Exception as e:
            logger.error(f"Error listing from LangGraph Store: {e}")
            return []
    
    async def delete(
        self,
        namespace: str,
        key: str
    ):
        """
        Удалить значение из store
        
        Args:
            namespace: Namespace
            key: Ключ
        """
        if not self.store:
            logger.debug("Store not available, skipping delete")
            return
        
        try:
            if hasattr(self.store, 'delete'):
                self.store.delete(namespace, key)
            elif hasattr(self.store, 'adelete'):
                await self.store.adelete(namespace, key)
            else:
                logger.warning("Store does not support delete operations")
                return
            
            logger.debug(f"Deleted from LangGraph Store: {namespace}/{key}")
        except Exception as e:
            logger.error(f"Error deleting from LangGraph Store: {e}")







































