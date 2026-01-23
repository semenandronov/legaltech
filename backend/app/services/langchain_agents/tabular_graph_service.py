"""
TabularGraphService - сервис для интеграции TabularGraph в API endpoints.

Предоставляет унифицированный интерфейс для:
- Запуска извлечения данных через TabularGraph
- Обработки HITL (Human-in-the-Loop) через interrupt/resume
- Streaming событий для UI
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from langgraph.types import Command
from app.services.rag_service import RAGService
from app.services.langchain_agents.graphs.tabular_graph import (
    create_tabular_graph,
    create_initial_tabular_state,
    TabularGraphState
)
from app.models.user import User
import logging
import json
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


class TabularGraphService:
    """
    Сервис для работы с TabularGraph.
    
    Обеспечивает:
    - Запуск извлечения данных
    - Обработку HITL через interrupt/resume
    - Streaming событий прогресса
    """
    
    _graph_instance = None
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None
    ):
        """
        Инициализация сервиса.
        
        Args:
            db: Database session
            rag_service: RAG service instance
        """
        self.db = db
        self.rag_service = rag_service or RAGService()
    
    def _get_or_create_graph(self):
        """Получить или создать экземпляр графа."""
        if TabularGraphService._graph_instance is None:
            TabularGraphService._graph_instance = create_tabular_graph(
                db=self.db,
                use_checkpointing=True
            )
            logger.info("[TabularGraphService] Created new TabularGraph instance")
        return TabularGraphService._graph_instance
    
    async def start_extraction(
        self,
        review_id: str,
        case_id: str,
        user: User,
        columns: List[Dict[str, Any]],
        file_ids: List[str],
        confidence_threshold: float = 0.8,
        enable_hitl: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Запустить извлечение данных через TabularGraph.
        
        Args:
            review_id: ID табличного обзора
            case_id: ID дела
            user: Текущий пользователь
            columns: Конфигурация колонок
            file_ids: ID файлов для обработки
            confidence_threshold: Порог уверенности для HITL
            enable_hitl: Включить HITL
        
        Yields:
            JSON строки с событиями прогресса
        """
        logger.info(f"[TabularGraphService] Starting extraction for review {review_id}")
        
        # Создаём начальное состояние
        initial_state = create_initial_tabular_state(
            review_id=review_id,
            case_id=case_id,
            user_id=str(user.id),
            columns=columns,
            file_ids=file_ids,
            confidence_threshold=confidence_threshold,
            enable_hitl=enable_hitl
        )
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        # Генерируем thread_id для checkpointing
        thread_id = f"tabular_{review_id}_{datetime.utcnow().timestamp()}"
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 50
        }
        
        try:
            # Streaming через граф
            async for chunk in graph.astream(initial_state, config=config):
                if isinstance(chunk, dict):
                    for node_name, node_data in chunk.items():
                        if not isinstance(node_data, dict):
                            continue
                        
                        # Отправляем фазу
                        phase = node_data.get("current_phase")
                        if phase:
                            yield f"data: {json.dumps({'type': 'phase', 'phase': phase})}\n\n"
                        
                        # Отправляем сообщения
                        messages = node_data.get("messages", [])
                        for msg in messages:
                            if hasattr(msg, 'content') and msg.content:
                                yield f"data: {json.dumps({'type': 'message', 'content': msg.content})}\n\n"
                        
                        # Отправляем результаты валидации
                        validation = node_data.get("validation_result")
                        if validation:
                            yield f"data: {json.dumps({'type': 'validation', 'result': validation})}\n\n"
                        
                        # Отправляем результаты извлечения
                        extraction = node_data.get("extraction_results")
                        if extraction:
                            yield f"data: {json.dumps({'type': 'extraction', 'count': len(extraction)})}\n\n"
                        
                        # Отправляем запросы на уточнение (HITL)
                        clarifications = node_data.get("clarification_requests")
                        if clarifications:
                            yield f"data: {json.dumps({'type': 'clarification_requests', 'requests': clarifications, 'thread_id': thread_id})}\n\n"
                        
                        # Отправляем результаты сохранения
                        saved = node_data.get("saved_count")
                        if saved is not None:
                            yield f"data: {json.dumps({'type': 'saved', 'count': saved})}\n\n"
                        
                        # Отправляем ошибки
                        errors = node_data.get("errors")
                        if errors:
                            yield f"data: {json.dumps({'type': 'errors', 'errors': errors})}\n\n"
            
            # Финальное событие
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
            logger.info(f"[TabularGraphService] Extraction completed for review {review_id}")
            
        except Exception as e:
            logger.error(f"[TabularGraphService] Extraction error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    async def resume_with_clarifications(
        self,
        thread_id: str,
        clarification_responses: Dict[str, Dict[str, Any]]
    ) -> AsyncGenerator[str, None]:
        """
        Возобновить выполнение после HITL с ответами пользователя.
        
        Args:
            thread_id: ID потока (из события clarification_requests)
            clarification_responses: Ответы пользователя {request_id: {value, confirmed}}
        
        Yields:
            JSON строки с событиями прогресса
        """
        logger.info(f"[TabularGraphService] Resuming with clarifications for thread {thread_id}")
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        config = {
            "configurable": {"thread_id": thread_id}
        }
        
        try:
            # Создаём Command для resume
            resume_command = Command(
                resume={
                    "clarification_responses": clarification_responses,
                    "plan_approved": True  # Для совместимости с workflow
                }
            )
            
            # Продолжаем выполнение
            async for chunk in graph.astream(resume_command, config=config):
                if isinstance(chunk, dict):
                    for node_name, node_data in chunk.items():
                        if not isinstance(node_data, dict):
                            continue
                        
                        # Отправляем фазу
                        phase = node_data.get("current_phase")
                        if phase:
                            yield f"data: {json.dumps({'type': 'phase', 'phase': phase})}\n\n"
                        
                        # Отправляем сообщения
                        messages = node_data.get("messages", [])
                        for msg in messages:
                            if hasattr(msg, 'content') and msg.content:
                                yield f"data: {json.dumps({'type': 'message', 'content': msg.content})}\n\n"
                        
                        # Отправляем результаты сохранения
                        saved = node_data.get("saved_count")
                        if saved is not None:
                            yield f"data: {json.dumps({'type': 'saved', 'count': saved})}\n\n"
            
            # Финальное событие
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
            logger.info(f"[TabularGraphService] Resume completed for thread {thread_id}")
            
        except Exception as e:
            logger.error(f"[TabularGraphService] Resume error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"


def get_tabular_graph_service(
    db: Session,
    rag_service: RAGService = None
) -> TabularGraphService:
    """
    Получить экземпляр TabularGraphService.
    
    Args:
        db: Database session
        rag_service: RAG service instance
    
    Returns:
        TabularGraphService instance
    """
    return TabularGraphService(
        db=db,
        rag_service=rag_service or RAGService()
    )



