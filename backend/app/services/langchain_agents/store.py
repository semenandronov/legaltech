"""CaseStore - абстракция над RAG/DB для долгосрочной памяти дела"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from langchain_core.documents import Document
from app.services.rag_service import RAGService
from app.services.langchain_agents.context_schema import CaseContext
from app.models.case import Case
from app.models.analysis import ExtractedEntity
import logging

logger = logging.getLogger(__name__)


class CaseStore:
    """
    Store для долгосрочной памяти дела:
    - Извлечённые сущности
    - События анализа
    - История взаимодействий
    - Результаты предыдущих анализов
    
    Предоставляет унифицированный интерфейс для работы с данными дела,
    абстрагируя детали RAGService и базы данных.
    """
    
    def __init__(self, db: Session, case_id: str, rag_service: RAGService):
        """
        Инициализация CaseStore
        
        Args:
            db: Сессия базы данных
            case_id: Идентификатор дела
            rag_service: Экземпляр RAGService для поиска документов
        """
        self.db = db
        self.case_id = case_id
        self.rag_service = rag_service
        self._cache_service = None
        
        # Инициализация cache service если доступен
        try:
            from app.services.langchain_agents.store_cache_service import StoreCacheService
            self._cache_service = StoreCacheService(db)
            logger.debug(f"Cache service initialized for CaseStore (case_id={case_id})")
        except Exception as e:
            logger.debug(f"Cache service not available for CaseStore: {e}")
    
    def search(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        k: int = 20,
        retrieval_strategy: str = "multi_query",
        use_iterative: bool = False,
        use_hybrid: bool = False
    ) -> List[Document]:
        """
        Унифицированный поиск по хранилищу дела
        
        Args:
            query: Поисковый запрос
            filters: Опциональные фильтры (например, {"doc_types": ["contract"]})
            k: Количество документов для извлечения
            retrieval_strategy: Стратегия поиска (simple, multi_query, iterative, hybrid)
            use_iterative: Использовать итеративный поиск
            use_hybrid: Использовать гибридный поиск
            
        Returns:
            Список релевантных документов
        """
        try:
            # Извлекаем doc_types из filters если есть
            doc_types = None
            if filters and "doc_types" in filters:
                doc_types = filters["doc_types"]
            
            # Используем RAGService для поиска
            documents = self.rag_service.retrieve_context(
                case_id=self.case_id,
                query=query,
                k=k,
                retrieval_strategy=retrieval_strategy,
                db=self.db,
                use_iterative=use_iterative,
                use_hybrid=use_hybrid,
                doc_types=doc_types
            )
            
            logger.debug(f"CaseStore.search: found {len(documents)} documents for query '{query[:50]}...'")
            return documents
            
        except Exception as e:
            logger.error(f"Error in CaseStore.search: {e}", exc_info=True)
            return []
    
    def get_entities(self) -> List[Dict[str, Any]]:
        """
        Получить извлечённые сущности из предыдущих анализов
        
        Returns:
            Список словарей с сущностями (имена, организации, суммы, даты)
        """
        try:
            # Получаем entities из базы данных
            entities = self.db.query(ExtractedEntity).filter(
                ExtractedEntity.case_id == self.case_id
            ).all()
            
            # Преобразуем в список словарей
            result = []
            for entity in entities:
                result.append({
                    "id": entity.id,
                    "entity_type": entity.entity_type,
                    "entity_text": entity.entity_text,
                    "file_id": entity.file_id,
                    "context": entity.context,
                    "confidence": entity.confidence,
                    "source_document": entity.source_document,
                    "source_page": entity.source_page,
                    "source_line": entity.source_line
                })
            
            logger.debug(f"CaseStore.get_entities: retrieved {len(result)} entities for case {self.case_id}")
            return result
            
        except Exception as e:
            logger.error(f"Error in CaseStore.get_entities: {e}", exc_info=True)
            return []
    
    def save_analysis_event(
        self,
        event_type: str,
        data: Dict[str, Any]
    ) -> None:
        """
        Сохранить событие анализа в историю
        
        Args:
            event_type: Тип события (например, "agent_started", "agent_completed", "error")
            data: Данные события
        """
        try:
            # TODO: Можно создать отдельную таблицу analysis_events для хранения событий
            # Пока логируем в лог-файл или используем существующие механизмы
            logger.info(
                f"Analysis event: case_id={self.case_id}, type={event_type}, data={data}"
            )
            
            # Можно также сохранить в case_metadata если нужно
            # case = self.db.query(Case).filter(Case.id == self.case_id).first()
            # if case:
            #     if not case.case_metadata:
            #         case.case_metadata = {}
            #     if "analysis_events" not in case.case_metadata:
            #         case.case_metadata["analysis_events"] = []
            #     case.case_metadata["analysis_events"].append({
            #         "type": event_type,
            #         "data": data,
            #         "timestamp": datetime.utcnow().isoformat()
            #     })
            #     self.db.commit()
            
        except Exception as e:
            logger.error(f"Error in CaseStore.save_analysis_event: {e}", exc_info=True)
    
    def get_previous_results(self, analysis_type: str) -> Optional[Dict[str, Any]]:
        """
        Получить результаты предыдущего анализа (для кэширования)
        
        Args:
            analysis_type: Тип анализа (timeline, key_facts, discrepancy, risk, summary, и т.д.)
            
        Returns:
            Результаты предыдущего анализа или None если не найдены
        """
        try:
            if not self._cache_service:
                return None
            
            # Используем cache service для получения кэшированных результатов
            # Формируем ключ для кэша
            cache_key = f"{analysis_type}_{self.case_id}"
            
            # Пытаемся получить из кэша через store_cache_service
            # Это требует знания о том, как cache service хранит данные
            # Пока возвращаем None, можно расширить позже
            
            # Альтернативный подход: использовать AnalysisResult из базы данных
            from app.models.analysis import AnalysisResult
            result = self.db.query(AnalysisResult).filter(
                AnalysisResult.case_id == self.case_id,
                AnalysisResult.analysis_type == analysis_type
            ).order_by(AnalysisResult.created_at.desc()).first()
            
            if result:
                return {
                    "result": result.result,
                    "created_at": result.created_at.isoformat() if result.created_at else None,
                    "analysis_type": result.analysis_type
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in CaseStore.get_previous_results: {e}", exc_info=True)
            return None
    
    def get_case_info(self) -> Dict[str, Any]:
        """
        Получить метаданные дела
        
        Returns:
            Словарь с метаданными дела
        """
        try:
            case = self.db.query(Case).filter(Case.id == self.case_id).first()
            if not case:
                return {}
            
            return {
                "case_id": case.id,
                "user_id": case.user_id,
                "title": case.title,
                "description": case.description,
                "case_type": case.case_type,
                "status": case.status,
                "num_documents": case.num_documents,
                "file_names": case.file_names,
                "created_at": case.created_at.isoformat() if case.created_at else None,
                "updated_at": case.updated_at.isoformat() if case.updated_at else None,
                "case_metadata": case.case_metadata
            }
            
        except Exception as e:
            logger.error(f"Error in CaseStore.get_case_info: {e}", exc_info=True)
            return {}

