"""Fact Store for storing structured facts in Store with embeddings"""
from typing import List, Dict, Any, Optional
from app.services.langchain_agents.store_integration import get_store_instance, save_to_store, load_from_store
import json
import logging

logger = logging.getLogger(__name__)


class FactStore:
    """
    Store для структурированных фактов
    
    Сохраняет структурированные факты (entities, key_facts, timeline events)
    в LangGraph Store с embeddings для semantic search.
    Namespace по case_id для изоляции.
    """
    
    def __init__(self, case_id: str):
        """
        Инициализация FactStore
        
        Args:
            case_id: ID дела для namespace
        """
        self.case_id = case_id
        self.store = get_store_instance()
        self.namespace = f"facts/{case_id}"
    
    def save_facts(
        self,
        fact_type: str,
        facts: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Сохранить структурированные факты
        
        Args:
            fact_type: Тип фактов (entities, key_facts, timeline_events)
            facts: Список фактов
            metadata: Дополнительные метаданные
        
        Returns:
            True если сохранено успешно
        """
        if not self.store:
            logger.debug("Store not available, skipping fact storage")
            return False
        
        try:
            # Сохранить факты в Store
            key = f"{fact_type}_facts"
            value = {
                "fact_type": fact_type,
                "facts": facts,
                "count": len(facts),
                "metadata": metadata or {}
            }
            
            saved = save_to_store(
                self.store,
                self.namespace,
                key,
                value,
                self.case_id
            )
            
            if saved:
                logger.debug(f"Saved {len(facts)} {fact_type} facts to Store (case: {self.case_id})")
            
            return saved
            
        except Exception as e:
            logger.error(f"Error saving facts to Store: {e}", exc_info=True)
            return False
    
    def load_facts(
        self,
        fact_type: str
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Загрузить структурированные факты
        
        Args:
            fact_type: Тип фактов (entities, key_facts, timeline_events)
        
        Returns:
            Список фактов или None если не найдено
        """
        if not self.store:
            logger.debug("Store not available, cannot load facts")
            return None
        
        try:
            key = f"{fact_type}_facts"
            value = load_from_store(
                self.store,
                self.namespace,
                key,
                self.case_id
            )
            
            if value and isinstance(value, dict):
                facts = value.get("facts", [])
                logger.debug(f"Loaded {len(facts)} {fact_type} facts from Store (case: {self.case_id})")
                return facts
            
            return None
            
        except Exception as e:
            logger.error(f"Error loading facts from Store: {e}", exc_info=True)
            return None
    
    def search_facts(
        self,
        fact_type: str,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Поиск фактов по семантическому запросу
        
        Args:
            fact_type: Тип фактов
            query: Поисковый запрос
            limit: Максимальное количество результатов
        
        Returns:
            Список найденных фактов
        """
        # Загрузить все факты типа
        all_facts = self.load_facts(fact_type)
        
        if not all_facts:
            return []
        
        # Простой текстовый поиск (в production можно использовать embeddings)
        query_lower = query.lower()
        matching_facts = []
        
        for fact in all_facts:
            # Поиск в текстовых полях факта
            fact_text = json.dumps(fact, ensure_ascii=False).lower()
            if query_lower in fact_text:
                matching_facts.append(fact)
        
        return matching_facts[:limit]
    
    def get_all_fact_types(self) -> List[str]:
        """
        Получить список всех типов фактов для дела
        
        Returns:
            Список типов фактов
        """
        if not self.store:
            return []
        
        try:
            from app.services.langchain_agents.store_integration import search_in_store
            
            # Поиск всех ключей в namespace
            items = search_in_store(
                self.store,
                self.namespace,
                query=None,
                case_id=self.case_id,
                limit=100
            )
            
            # Извлечь типы фактов из ключей
            fact_types = []
            for item in items:
                if isinstance(item, dict) and "_facts" in str(item):
                    # Извлечь тип из ключа
                    key = item.get("key", "")
                    if key.endswith("_facts"):
                        fact_type = key.replace("_facts", "")
                        fact_types.append(fact_type)
            
            return list(set(fact_types))
            
        except Exception as e:
            logger.error(f"Error getting fact types: {e}", exc_info=True)
            return []


def get_fact_store(case_id: str) -> FactStore:
    """
    Получить FactStore для дела
    
    Args:
        case_id: ID дела
    
    Returns:
        FactStore instance
    """
    return FactStore(case_id)






































