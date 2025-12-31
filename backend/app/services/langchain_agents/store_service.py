"""LangGraph Store Service for long-term memory and pattern storage"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class LangGraphStoreService:
    """Сервис для долгосрочной памяти через LangGraph Store и PostgreSQL"""
    
    def __init__(self, db: Session):
        """Initialize store service
        
        Args:
            db: Database session
        """
        self.db = db
        self._ensure_tables()
        logger.info("✅ LangGraph Store Service initialized")
    
    def _ensure_tables(self):
        """Создает таблицы для Store если их нет"""
        try:
            # Проверяем, не находится ли сессия в состоянии 'prepared'
            # Если да, то создаем новую сессию для создания таблиц
            from sqlalchemy.orm import Session
            from app.utils.database import SessionLocal
            
            db_to_use = self.db
            should_close = False
            
            # Проверяем состояние сессии
            if hasattr(self.db, 'in_transaction') and self.db.in_transaction():
                # Сессия в транзакции, используем новую сессию
                db_to_use = SessionLocal()
                should_close = True
            
            try:
                # Таблица для паттернов и прецедентов
                db_to_use.execute(text("""
                    CREATE TABLE IF NOT EXISTS langgraph_store (
                        id SERIAL PRIMARY KEY,
                        namespace VARCHAR(255) NOT NULL,
                        key VARCHAR(500) NOT NULL,
                        value JSONB NOT NULL,
                        metadata JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(namespace, key)
                    )
                """))
                
                # Индексы для быстрого поиска
                db_to_use.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_store_namespace 
                    ON langgraph_store(namespace)
                """))
                
                db_to_use.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_store_key 
                    ON langgraph_store(key)
                """))
                
                # GIN индекс для JSONB поиска
                db_to_use.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_store_value_gin 
                    ON langgraph_store USING GIN(value)
                """))
                
                db_to_use.commit()
                logger.info("✅ LangGraph Store tables created")
            except Exception as e:
                try:
                    db_to_use.rollback()
                except Exception:
                    pass
                raise
            finally:
                if should_close:
                    db_to_use.close()
        except Exception as e:
            logger.warning(f"Store tables may already exist: {e}")
    
    async def save_pattern(
        self,
        namespace: str,
        key: str,
        value: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Сохранить паттерн для будущего использования
        
        Args:
            namespace: Namespace для группировки (например, "risk_patterns/employment_contract")
            key: Уникальный ключ паттерна (например, "Missing non-compete clause")
            value: Значение паттерна (например, {"severity": "high", "outcome": "loss"})
            metadata: Дополнительные метаданные
            
        Returns:
            True if saved successfully
        """
        try:
            # Проверяем состояние сессии и делаем rollback если нужно
            if not self.db.is_active:
                self.db.rollback()
            
            # Проверяем, существует ли уже такой паттерн
            existing = self.db.execute(
                text("""
                    SELECT id, value, updated_at 
                    FROM langgraph_store 
                    WHERE namespace = :namespace AND key = :key
                """),
                {"namespace": namespace, "key": key}
            ).fetchone()
            
            if existing:
                # Обновляем существующий паттерн
                self.db.execute(
                    text("""
                        UPDATE langgraph_store 
                        SET value = :value, 
                            metadata = :metadata,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE namespace = :namespace AND key = :key
                    """),
                    {
                        "namespace": namespace,
                        "key": key,
                        "value": json.dumps(value),
                        "metadata": json.dumps(metadata) if metadata else None
                    }
                )
                logger.debug(f"Updated pattern: {namespace}/{key}")
            else:
                # Создаем новый паттерн
                self.db.execute(
                    text("""
                        INSERT INTO langgraph_store (namespace, key, value, metadata)
                        VALUES (:namespace, :key, :value, :metadata)
                    """),
                    {
                        "namespace": namespace,
                        "key": key,
                        "value": json.dumps(value),
                        "metadata": json.dumps(metadata) if metadata else None
                    }
                )
                logger.debug(f"Saved new pattern: {namespace}/{key}")
            
            self.db.commit()
            return True
            
        except Exception as e:
            try:
                self.db.rollback()
            except Exception:
                pass  # Ignore rollback errors if commit already succeeded
            logger.error(f"Error saving pattern {namespace}/{key}: {e}", exc_info=True)
            return False
    
    async def search_precedents(
        self,
        namespace: str,
        query: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Найти похожие прецеденты
        
        Args:
            namespace: Namespace для поиска
            query: Опциональный поисковый запрос (поиск в value JSONB)
            limit: Максимальное количество результатов
            
        Returns:
            List of precedent dictionaries
        """
        try:
            # Проверяем состояние сессии и делаем rollback если нужно
            if not self.db.is_active:
                self.db.rollback()
            
            if query:
                # Поиск по содержимому JSONB value
                results = self.db.execute(
                    text("""
                        SELECT key, value, metadata, created_at, updated_at
                        FROM langgraph_store
                        WHERE namespace = :namespace
                        AND (
                            value::text ILIKE :query
                            OR key ILIKE :query
                        )
                        ORDER BY updated_at DESC
                        LIMIT :limit
                    """),
                    {
                        "namespace": namespace,
                        "query": f"%{query}%",
                        "limit": limit
                    }
                ).fetchall()
            else:
                # Получить все паттерны из namespace
                results = self.db.execute(
                    text("""
                        SELECT key, value, metadata, created_at, updated_at
                        FROM langgraph_store
                        WHERE namespace = :namespace
                        ORDER BY updated_at DESC
                        LIMIT :limit
                    """),
                    {
                        "namespace": namespace,
                        "limit": limit
                    }
                ).fetchall()
            
            precedents = []
            for row in results:
                precedents.append({
                    "key": row[0],
                    "value": json.loads(row[1]) if isinstance(row[1], str) else row[1],
                    "metadata": json.loads(row[2]) if row[2] and isinstance(row[2], str) else row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "updated_at": row[4].isoformat() if row[4] else None
                })
            
            logger.debug(f"Found {len(precedents)} precedents in namespace {namespace}")
            return precedents
            
        except Exception as e:
            logger.error(f"Error searching precedents in {namespace}: {e}", exc_info=True)
            return []
    
    async def get_pattern(
        self,
        namespace: str,
        key: str
    ) -> Optional[Dict[str, Any]]:
        """Получить конкретный паттерн"""
        try:
            result = self.db.execute(
                text("""
                    SELECT value, metadata, updated_at
                    FROM langgraph_store
                    WHERE namespace = :namespace AND key = :key
                """),
                {"namespace": namespace, "key": key}
            ).fetchone()
            
            if result:
                return {
                    "value": json.loads(result[0]) if isinstance(result[0], str) else result[0],
                    "metadata": json.loads(result[1]) if result[1] and isinstance(result[1], str) else result[1],
                    "updated_at": result[2].isoformat() if result[2] else None
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting pattern {namespace}/{key}: {e}")
            return None
    
    async def delete_pattern(
        self,
        namespace: str,
        key: str
    ) -> bool:
        """Удалить паттерн"""
        try:
            # Проверяем состояние сессии и делаем rollback если нужно
            if not self.db.is_active:
                self.db.rollback()
            
            self.db.execute(
                text("""
                    DELETE FROM langgraph_store
                    WHERE namespace = :namespace AND key = :key
                """),
                {"namespace": namespace, "key": key}
            )
            self.db.commit()
            logger.debug(f"Deleted pattern: {namespace}/{key}")
            return True
            
        except Exception as e:
            try:
                self.db.rollback()
            except Exception:
                pass  # Ignore rollback errors if commit already succeeded
            logger.error(f"Error deleting pattern {namespace}/{key}: {e}")
            return False
    
    async def list_namespaces(self) -> List[str]:
        """Получить список всех namespaces"""
        try:
            results = self.db.execute(
                text("""
                    SELECT DISTINCT namespace
                    FROM langgraph_store
                    ORDER BY namespace
                """)
            ).fetchall()
            
            return [row[0] for row in results]
            
        except Exception as e:
            logger.error(f"Error listing namespaces: {e}")
            return []
    
    async def count_patterns(self, namespace: Optional[str] = None) -> int:
        """Подсчитать количество паттернов"""
        try:
            if namespace:
                result = self.db.execute(
                    text("""
                        SELECT COUNT(*) FROM langgraph_store
                        WHERE namespace = :namespace
                    """),
                    {"namespace": namespace}
                ).scalar()
            else:
                result = self.db.execute(
                    text("SELECT COUNT(*) FROM langgraph_store")
                ).scalar()
            
            return result or 0
            
        except Exception as e:
            logger.error(f"Error counting patterns: {e}")
            return 0

