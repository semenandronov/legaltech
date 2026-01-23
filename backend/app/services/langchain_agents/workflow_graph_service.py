"""
WorkflowGraphService - сервис для интеграции WorkflowGraph в API endpoints.

Предоставляет унифицированный интерфейс для:
- Запуска workflows через WorkflowGraph
- Обработки HITL для одобрения плана
- Streaming событий прогресса
"""
from typing import AsyncGenerator, Optional, List, Dict, Any
from sqlalchemy.orm import Session
from langgraph.types import Command
from app.services.rag_service import RAGService
from app.services.langchain_agents.graphs.workflow_graph import (
    create_workflow_graph,
    create_initial_workflow_state,
    WorkflowGraphState
)
from app.models.user import User
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class WorkflowGraphService:
    """
    Сервис для работы с WorkflowGraph.
    
    Обеспечивает:
    - Запуск workflows
    - Обработку HITL для одобрения плана
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
        if WorkflowGraphService._graph_instance is None:
            WorkflowGraphService._graph_instance = create_workflow_graph(
                db=self.db,
                rag_service=self.rag_service,
                use_checkpointing=True
            )
            logger.info("[WorkflowGraphService] Created new WorkflowGraph instance")
        return WorkflowGraphService._graph_instance
    
    async def start_workflow(
        self,
        workflow_id: str,
        case_id: str,
        user: User,
        workflow_definition: Dict[str, Any],
        require_approval: bool = True,
        max_parallel_steps: int = 3,
        auto_adapt: bool = True
    ) -> AsyncGenerator[str, None]:
        """
        Запустить workflow через WorkflowGraph.
        
        Args:
            workflow_id: ID workflow
            case_id: ID дела
            user: Текущий пользователь
            workflow_definition: Определение workflow
            require_approval: Требовать одобрения плана
            max_parallel_steps: Максимум параллельных шагов
            auto_adapt: Автоматическая адаптация при ошибках
        
        Yields:
            JSON строки с событиями прогресса
        """
        logger.info(f"[WorkflowGraphService] Starting workflow {workflow_id}")
        
        # Создаём начальное состояние
        initial_state = create_initial_workflow_state(
            workflow_id=workflow_id,
            case_id=case_id,
            user_id=str(user.id),
            workflow_definition=workflow_definition,
            require_approval=require_approval,
            max_parallel_steps=max_parallel_steps,
            auto_adapt=auto_adapt
        )
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        # Генерируем thread_id для checkpointing
        thread_id = f"workflow_{workflow_id}_{datetime.utcnow().timestamp()}"
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": 100
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
                        
                        # Отправляем план для одобрения
                        plan = node_data.get("plan")
                        if plan and phase == "generate_plan":
                            yield f"data: {json.dumps({'type': 'plan', 'plan': plan, 'thread_id': thread_id})}\n\n"
                        
                        # Отправляем статистику выполнения
                        stats = node_data.get("execution_stats")
                        if stats:
                            yield f"data: {json.dumps({'type': 'stats', 'stats': stats})}\n\n"
                        
                        # Отправляем результаты шагов
                        step_results = node_data.get("step_results")
                        if step_results:
                            yield f"data: {json.dumps({'type': 'step_results', 'results': step_results})}\n\n"
                        
                        # Отправляем ошибки шагов
                        step_errors = node_data.get("step_errors")
                        if step_errors:
                            yield f"data: {json.dumps({'type': 'step_errors', 'errors': step_errors})}\n\n"
                        
                        # Отправляем финальный результат
                        final_result = node_data.get("final_result")
                        if final_result:
                            yield f"data: {json.dumps({'type': 'final_result', 'result': final_result})}\n\n"
            
            # Финальное событие
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
            logger.info(f"[WorkflowGraphService] Workflow {workflow_id} completed")
            
        except Exception as e:
            logger.error(f"[WorkflowGraphService] Workflow error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    async def approve_plan(
        self,
        thread_id: str,
        approved: bool = True,
        modifications: Dict[str, Any] = None
    ) -> AsyncGenerator[str, None]:
        """
        Одобрить или отклонить план и продолжить выполнение.
        
        Args:
            thread_id: ID потока (из события plan)
            approved: Одобрен ли план
            modifications: Модификации к плану
        
        Yields:
            JSON строки с событиями прогресса
        """
        logger.info(f"[WorkflowGraphService] {'Approving' if approved else 'Rejecting'} plan for thread {thread_id}")
        
        # Получаем граф
        graph = self._get_or_create_graph()
        
        config = {
            "configurable": {"thread_id": thread_id}
        }
        
        try:
            # Создаём Command для resume
            resume_command = Command(
                resume={
                    "plan_approved": approved,
                    "plan_modifications": modifications or {}
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
                        
                        # Отправляем статистику
                        stats = node_data.get("execution_stats")
                        if stats:
                            yield f"data: {json.dumps({'type': 'stats', 'stats': stats})}\n\n"
                        
                        # Отправляем результаты шагов
                        step_results = node_data.get("step_results")
                        if step_results:
                            yield f"data: {json.dumps({'type': 'step_results', 'results': step_results})}\n\n"
                        
                        # Отправляем ошибки шагов
                        step_errors = node_data.get("step_errors")
                        if step_errors:
                            yield f"data: {json.dumps({'type': 'step_errors', 'errors': step_errors})}\n\n"
                        
                        # Отправляем финальный результат
                        final_result = node_data.get("final_result")
                        if final_result:
                            yield f"data: {json.dumps({'type': 'final_result', 'result': final_result})}\n\n"
            
            # Финальное событие
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
            
            logger.info(f"[WorkflowGraphService] Plan approval processed for thread {thread_id}")
            
        except Exception as e:
            logger.error(f"[WorkflowGraphService] Plan approval error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"


def get_workflow_graph_service(
    db: Session,
    rag_service: RAGService = None
) -> WorkflowGraphService:
    """
    Получить экземпляр WorkflowGraphService.
    
    Args:
        db: Database session
        rag_service: RAG service instance
    
    Returns:
        WorkflowGraphService instance
    """
    return WorkflowGraphService(
        db=db,
        rag_service=rag_service or RAGService()
    )



