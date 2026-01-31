"""
Memory Store для долгосрочной памяти.

Реализует паттерн LangGraph Store для хранения данных памяти
с поддержкой namespace и версионирования.
"""
from typing import Optional, List, Dict, Any, TypeVar, Type
from datetime import datetime
from sqlalchemy.orm import Session
import json
import logging
import uuid

from app.services.langchain_agents.memory.schemas import (
    UserProfile,
    CaseMemory,
    QueryRecord,
    Insight,
    MemoryNamespace,
)

logger = logging.getLogger(__name__)

T = TypeVar('T')


class MemoryStore:
    """
    Store для долгосрочной памяти агентов.
    
    Использует PostgreSQL для персистентности с JSON-полями
    для хранения структурированных данных.
    
    # ПАТТЕРН NAMESPACE
    Данные организованы по namespace:
    - user_profile/{user_id}: Профили пользователей
    - case_memory/{case_id}: Память по делам
    - query_history/{user_id}: История запросов
    - insights/{scope_id}: Инсайты
    
    # ПРИМЕР
    ```python
    store = MemoryStore(db)
    
    # Получение профиля
    profile = store.get_user_profile("user-123")
    
    # Обновление
    profile.legal_preferences.primary_area = "corporate"
    store.put_user_profile(profile)
    ```
    """
    
    def __init__(self, db: Session = None):
        """
        Инициализация store.
        
        Args:
            db: SQLAlchemy session
        """
        self.db = db
        self._cache: Dict[str, Any] = {}
    
    def _get_key(self, namespace: MemoryNamespace, id: str) -> str:
        """Создать ключ для хранения."""
        return f"{namespace.value}/{id}"
    
    def _get_from_db(self, key: str) -> Optional[Dict[str, Any]]:
        """Получить данные из БД."""
        if not self.db:
            return None
        
        try:
            from app.models.langgraph_store import LangGraphStoreEntry
            
            entry = self.db.query(LangGraphStoreEntry).filter(
                LangGraphStoreEntry.key == key
            ).first()
            
            if entry:
                return json.loads(entry.value)
            return None
            
        except Exception as e:
            logger.warning(f"[MemoryStore] DB get error for {key}: {e}")
            return None
    
    def _put_to_db(self, key: str, value: Dict[str, Any]) -> bool:
        """Сохранить данные в БД."""
        if not self.db:
            return False
        
        try:
            from app.models.langgraph_store import LangGraphStoreEntry
            
            entry = self.db.query(LangGraphStoreEntry).filter(
                LangGraphStoreEntry.key == key
            ).first()
            
            if entry:
                entry.value = json.dumps(value, default=str)
                entry.updated_at = datetime.utcnow()
            else:
                entry = LangGraphStoreEntry(
                    key=key,
                    value=json.dumps(value, default=str),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                self.db.add(entry)
            
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"[MemoryStore] DB put error for {key}: {e}")
            self.db.rollback()
            return False
    
    def _delete_from_db(self, key: str) -> bool:
        """Удалить данные из БД."""
        if not self.db:
            return False
        
        try:
            from app.models.langgraph_store import LangGraphStoreEntry
            
            self.db.query(LangGraphStoreEntry).filter(
                LangGraphStoreEntry.key == key
            ).delete()
            
            self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"[MemoryStore] DB delete error for {key}: {e}")
            self.db.rollback()
            return False
    
    # ============== User Profile ==============
    
    def get_user_profile(self, user_id: str) -> UserProfile:
        """
        Получить профиль пользователя.
        
        Создаёт новый профиль если не существует.
        """
        key = self._get_key(MemoryNamespace.USER_PROFILE, user_id)
        
        # Проверяем кэш
        if key in self._cache:
            return self._cache[key]
        
        # Получаем из БД
        data = self._get_from_db(key)
        
        if data:
            profile = UserProfile(**data)
        else:
            # Создаём новый профиль
            profile = UserProfile(user_id=user_id)
            self.put_user_profile(profile)
        
        self._cache[key] = profile
        return profile
    
    def put_user_profile(self, profile: UserProfile) -> bool:
        """Сохранить профиль пользователя."""
        key = self._get_key(MemoryNamespace.USER_PROFILE, profile.user_id)
        
        profile.updated_at = datetime.utcnow()
        
        self._cache[key] = profile
        return self._put_to_db(key, profile.model_dump())
    
    # ============== Case Memory ==============
    
    def get_case_memory(self, case_id: str, user_id: str) -> CaseMemory:
        """
        Получить память по делу.
        
        Создаёт новую память если не существует.
        """
        key = self._get_key(MemoryNamespace.CASE_MEMORY, case_id)
        
        # Проверяем кэш
        if key in self._cache:
            return self._cache[key]
        
        # Получаем из БД
        data = self._get_from_db(key)
        
        if data:
            memory = CaseMemory(**data)
        else:
            # Создаём новую память
            memory = CaseMemory(case_id=case_id, user_id=user_id)
            self.put_case_memory(memory)
        
        self._cache[key] = memory
        return memory
    
    def put_case_memory(self, memory: CaseMemory) -> bool:
        """Сохранить память по делу."""
        key = self._get_key(MemoryNamespace.CASE_MEMORY, memory.case_id)
        
        memory.updated_at = datetime.utcnow()
        
        self._cache[key] = memory
        return self._put_to_db(key, memory.model_dump())
    
    # ============== Query History ==============
    
    def add_query_record(self, record: QueryRecord) -> bool:
        """Добавить запись о запросе."""
        # История хранится как список
        key = self._get_key(MemoryNamespace.QUERY_HISTORY, record.user_id)
        
        data = self._get_from_db(key)
        
        if data:
            records = data.get("records", [])
        else:
            records = []
        
        # Добавляем новую запись (в начало)
        records.insert(0, record.model_dump())
        
        # Ограничиваем размер истории
        records = records[:100]  # Храним последние 100 записей
        
        return self._put_to_db(key, {"records": records, "updated_at": datetime.utcnow().isoformat()})
    
    def get_query_history(
        self,
        user_id: str,
        limit: int = 10,
        case_id: Optional[str] = None
    ) -> List[QueryRecord]:
        """Получить историю запросов."""
        key = self._get_key(MemoryNamespace.QUERY_HISTORY, user_id)
        
        data = self._get_from_db(key)
        
        if not data:
            return []
        
        records = data.get("records", [])
        
        # Фильтруем по case_id если указан
        if case_id:
            records = [r for r in records if r.get("case_id") == case_id]
        
        # Преобразуем в объекты
        result = []
        for r in records[:limit]:
            try:
                result.append(QueryRecord(**r))
            except Exception as e:
                logger.warning(f"[MemoryStore] Invalid query record: {e}")
        
        return result
    
    # ============== Insights ==============
    
    def add_insight(self, insight: Insight) -> bool:
        """Добавить инсайт."""
        key = self._get_key(MemoryNamespace.INSIGHTS, insight.scope_id)
        
        data = self._get_from_db(key)
        
        if data:
            insights = data.get("insights", [])
        else:
            insights = []
        
        # Проверяем на дубликаты по title
        existing_titles = {i.get("title") for i in insights}
        if insight.title in existing_titles:
            # Обновляем существующий
            insights = [
                insight.model_dump() if i.get("title") == insight.title else i
                for i in insights
            ]
        else:
            insights.append(insight.model_dump())
        
        return self._put_to_db(key, {"insights": insights, "updated_at": datetime.utcnow().isoformat()})
    
    def get_insights(
        self,
        scope_id: str,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 10
    ) -> List[Insight]:
        """Получить инсайты."""
        key = self._get_key(MemoryNamespace.INSIGHTS, scope_id)
        
        data = self._get_from_db(key)
        
        if not data:
            return []
        
        insights = data.get("insights", [])
        
        # Фильтруем
        if category:
            insights = [i for i in insights if i.get("category") == category]
        if priority:
            insights = [i for i in insights if i.get("priority") == priority]
        
        # Сортируем по приоритету
        priority_order = {"high": 0, "medium": 1, "low": 2}
        insights.sort(key=lambda x: priority_order.get(x.get("priority", "medium"), 1))
        
        # Преобразуем в объекты
        result = []
        for i in insights[:limit]:
            try:
                result.append(Insight(**i))
            except Exception as e:
                logger.warning(f"[MemoryStore] Invalid insight: {e}")
        
        return result
    
    # ============== Search ==============
    
    def search(
        self,
        namespace: MemoryNamespace,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Поиск по данным в namespace.
        
        Простой текстовый поиск. Для семантического поиска
        используйте RAG.
        """
        if not self.db:
            return []
        
        try:
            from app.models.langgraph_store import LangGraphStoreEntry
            
            # Получаем все записи в namespace
            entries = self.db.query(LangGraphStoreEntry).filter(
                LangGraphStoreEntry.key.like(f"{namespace.value}/%")
            ).all()
            
            results = []
            query_lower = query.lower()
            
            for entry in entries:
                try:
                    data = json.loads(entry.value)
                    # Простой поиск по JSON
                    data_str = json.dumps(data, ensure_ascii=False).lower()
                    if query_lower in data_str:
                        results.append({
                            "key": entry.key,
                            "data": data,
                            "updated_at": entry.updated_at
                        })
                except Exception:
                    continue
            
            return results[:limit]
            
        except Exception as e:
            logger.error(f"[MemoryStore] Search error: {e}")
            return []
    
    def clear_cache(self):
        """Очистить кэш."""
        self._cache.clear()


# Singleton instance
_store_instance: Optional[MemoryStore] = None


def get_memory_store(db: Session = None) -> MemoryStore:
    """
    Получить экземпляр MemoryStore.
    
    Args:
        db: Database session
    
    Returns:
        MemoryStore instance
    """
    global _store_instance
    
    if _store_instance is None or db is not None:
        _store_instance = MemoryStore(db)
    
    return _store_instance

