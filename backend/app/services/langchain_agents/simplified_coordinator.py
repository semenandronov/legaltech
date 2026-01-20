"""
Упрощённый координатор агентов для юридического анализа.

Заменяет сложный AgentCoordinator из coordinator.py:
- Без SubAgentManager
- Без AdvancedPlanningAgent  
- Без LearningService
- Без ContextManager
- Без сложной логики параллельного выполнения

Фокус на:
- Простоте и надёжности
- Точности результатов
- Лёгкости отладки
"""
from typing import Dict, Any, List, Optional, AsyncGenerator, Callable
from sqlalchemy.orm import Session
import logging
import time
import asyncio

from app.services.langchain_agents.simplified_graph import create_simplified_graph
from app.services.langchain_agents.state import AnalysisState, create_initial_state
from app.services.langchain_agents.core_agents import (
    CORE_AGENTS,
    ALL_AGENTS,
    validate_analysis_types,
    get_agents_with_dependencies,
)
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)


class SimplifiedAgentCoordinator:
    """
    Упрощённый координатор для запуска агентного анализа.
    
    Принципы:
    1. Минимум абстракций — код должен быть понятен
    2. Детерминированное поведение — одинаковый вход = одинаковый выход
    3. Явная обработка ошибок — никаких скрытых fallback'ов
    4. Простое логирование — легко отлаживать
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None,
    ):
        """
        Инициализация координатора.
        
        Args:
            db: Database session
            rag_service: RAG service для поиска в документах
            document_processor: Процессор документов
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Создаём граф
        self.graph = create_simplified_graph(db, rag_service, document_processor)
        
        logger.info("SimplifiedAgentCoordinator initialized")
    
    def run_analysis(
        self,
        case_id: str,
        analysis_types: List[str],
        user_task: Optional[str] = None,
        step_callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """
        Запустить синхронный анализ документов.
        
        Args:
            case_id: ID дела
            analysis_types: Список типов анализа (timeline, key_facts, etc.)
            user_task: Опциональное описание задачи от пользователя
            step_callback: Callback для уведомления о прогрессе
        
        Returns:
            Словарь с результатами:
            - final_state: Финальное состояние графа
            - execution_time: Время выполнения
            - completed_agents: Список выполненных агентов
            - errors: Список ошибок (если есть)
        """
        start_time = time.time()
        
        # === ВАЛИДАЦИЯ ===
        if not case_id or not isinstance(case_id, str):
            raise ValueError("case_id must be a non-empty string")
        
        # Проверяем существование дела
        from app.models.case import Case
        case = self.db.query(Case).filter(Case.id == case_id).first()
        if not case:
            raise ValueError(f"Case {case_id} not found")
        
        # Валидируем типы анализа
        is_valid, invalid_types = validate_analysis_types(analysis_types)
        if not is_valid:
            raise ValueError(f"Invalid analysis types: {invalid_types}. Valid: {list(ALL_AGENTS)}")
        
        # Добавляем зависимости
        full_analysis_types = get_agents_with_dependencies(analysis_types)
        
        if not full_analysis_types:
            raise ValueError("No valid analysis types after processing")
        
        logger.info(f"[SimplifiedCoordinator] Starting analysis for case {case_id}")
        logger.info(f"[SimplifiedCoordinator] Requested: {analysis_types}")
        logger.info(f"[SimplifiedCoordinator] With dependencies: {full_analysis_types}")
        
        # === СОЗДАНИЕ НАЧАЛЬНОГО СОСТОЯНИЯ ===
        initial_state = create_initial_state(
            case_id=case_id,
            analysis_types=full_analysis_types,
            metadata={
                "user_task": user_task,
                "original_request": analysis_types,
            },
        )
        
        # Конфиг для графа
        thread_config = {
            "configurable": {
                "thread_id": f"simplified_{case_id}_{int(time.time())}",
                "recursion_limit": 50,  # Достаточно для всех агентов
            }
        }
        
        # === ВЫПОЛНЕНИЕ ГРАФА ===
        final_state = None
        completed_agents = []
        errors = []
        
        try:
            for event in self.graph.stream(initial_state, thread_config):
                # Определяем какой узел завершился
                node_name = list(event.keys())[0] if event else "unknown"
                node_state = event.get(node_name, {})
                
                # Логируем прогресс
                if node_name in ALL_AGENTS:
                    completed_agents.append(node_name)
                    logger.info(f"[SimplifiedCoordinator] ✓ {node_name} completed")
                    
                    # Вызываем callback если есть
                    if step_callback:
                        try:
                            step_info = {
                                "agent_name": node_name,
                                "status": "completed",
                                "timestamp": time.time(),
                            }
                            step_callback(step_info)
                        except Exception as cb_error:
                            logger.warning(f"Step callback error: {cb_error}")
                
                final_state = node_state
            
            # Получаем финальное состояние из графа
            graph_state = self.graph.get_state(thread_config)
            if graph_state and graph_state.values:
                final_state = graph_state.values
            
        except Exception as e:
            logger.error(f"[SimplifiedCoordinator] Error during execution: {e}", exc_info=True)
            errors.append({
                "type": "execution_error",
                "message": str(e),
            })
        
        execution_time = time.time() - start_time
        
        # === ФОРМИРОВАНИЕ РЕЗУЛЬТАТА ===
        result = {
            "case_id": case_id,
            "final_state": final_state,
            "execution_time": execution_time,
            "completed_agents": completed_agents,
            "requested_agents": full_analysis_types,
            "errors": errors,
        }
        
        # Добавляем отдельные результаты для удобства
        if final_state:
            result["timeline"] = final_state.get("timeline_result")
            result["key_facts"] = final_state.get("key_facts_result")
            result["discrepancy"] = final_state.get("discrepancy_result")
            result["entities"] = final_state.get("entities_result")
            result["classification"] = final_state.get("classification_result")
            result["summary"] = final_state.get("summary_result")
            result["risk"] = final_state.get("risk_result")
            result["relationship"] = final_state.get("relationship_result")
            result["privilege"] = final_state.get("privilege_result")
        
        logger.info(
            f"[SimplifiedCoordinator] Analysis completed in {execution_time:.2f}s. "
            f"Completed: {len(completed_agents)}/{len(full_analysis_types)} agents"
        )
        
        return result
    
    async def stream_analysis(
        self,
        case_id: str,
        analysis_types: List[str],
        user_task: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Асинхронный streaming анализа с событиями.
        
        Yields:
            События прогресса:
            - {"type": "start", "case_id": ..., "agents": [...]}
            - {"type": "agent_start", "agent": "timeline"}
            - {"type": "agent_complete", "agent": "timeline", "result": {...}}
            - {"type": "complete", "execution_time": ...}
            - {"type": "error", "message": ...}
        """
        start_time = time.time()
        
        # Валидация
        try:
            if not case_id:
                raise ValueError("case_id is required")
            
            from app.models.case import Case
            case = self.db.query(Case).filter(Case.id == case_id).first()
            if not case:
                raise ValueError(f"Case {case_id} not found")
            
            is_valid, invalid_types = validate_analysis_types(analysis_types)
            if not is_valid:
                raise ValueError(f"Invalid analysis types: {invalid_types}")
            
            full_analysis_types = get_agents_with_dependencies(analysis_types)
            
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return
        
        # Событие старта
        yield {
            "type": "start",
            "case_id": case_id,
            "agents": full_analysis_types,
            "user_task": user_task,
        }
        
        # Создаём состояние
        initial_state = create_initial_state(
            case_id=case_id,
            analysis_types=full_analysis_types,
            metadata={"user_task": user_task},
        )
        
        thread_config = {
            "configurable": {
                "thread_id": f"stream_{case_id}_{int(time.time())}",
                "recursion_limit": 50,
            }
        }
        
        # Выполняем граф
        completed_agents = []
        final_state = None
        
        try:
            # Используем astream_events для асинхронного streaming
            async for event in self.graph.astream_events(
                initial_state,
                config=thread_config,
                version="v2",
            ):
                event_type = event.get("event", "")
                
                # Обрабатываем завершение узлов
                if event_type == "on_chain_end":
                    node_name = event.get("name", "")
                    
                    if node_name in ALL_AGENTS:
                        completed_agents.append(node_name)
                        output = event.get("data", {}).get("output", {})
                        
                        yield {
                            "type": "agent_complete",
                            "agent": node_name,
                            "result_preview": self._get_result_preview(node_name, output),
                        }
                
                # Обрабатываем токены (если нужен streaming текста)
                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield {
                            "type": "token",
                            "content": chunk.content,
                        }
            
            # Получаем финальное состояние
            graph_state = self.graph.get_state(thread_config)
            if graph_state:
                final_state = graph_state.values
            
        except Exception as e:
            logger.error(f"[SimplifiedCoordinator] Stream error: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)}
            return
        
        execution_time = time.time() - start_time
        
        # Финальное событие
        yield {
            "type": "complete",
            "case_id": case_id,
            "execution_time": execution_time,
            "completed_agents": completed_agents,
            "final_state": final_state,
        }
    
    def _get_result_preview(self, agent_name: str, output: Any) -> Dict[str, Any]:
        """Получить краткий preview результата агента."""
        if not isinstance(output, dict):
            return {"preview": "No preview available"}
        
        # Определяем ключ результата
        result_key = {
            "timeline": "timeline_result",
            "key_facts": "key_facts_result",
            "discrepancy": "discrepancy_result",
            "entity_extraction": "entities_result",
            "document_classifier": "classification_result",
            "summary": "summary_result",
        }.get(agent_name)
        
        if not result_key:
            return {"preview": "Unknown agent"}
        
        result = output.get(result_key, {})
        
        # Формируем preview в зависимости от типа
        if agent_name == "timeline":
            events = result.get("events", [])
            return {"count": len(events), "preview": f"{len(events)} events extracted"}
        
        elif agent_name == "key_facts":
            facts = result.get("facts", [])
            return {"count": len(facts), "preview": f"{len(facts)} key facts found"}
        
        elif agent_name == "discrepancy":
            discs = result.get("discrepancies", [])
            return {"count": len(discs), "preview": f"{len(discs)} discrepancies found"}
        
        elif agent_name == "entity_extraction":
            entities = result.get("entities", [])
            return {"count": len(entities), "preview": f"{len(entities)} entities extracted"}
        
        elif agent_name == "document_classifier":
            classifications = result.get("classifications", [])
            return {"count": len(classifications), "preview": f"{len(classifications)} documents classified"}
        
        elif agent_name == "summary":
            summary = result.get("summary", "")
            return {"preview": summary[:200] + "..." if len(summary) > 200 else summary}
        
        return {"preview": "Result available"}


# =============================================================================
# ФАБРИЧНАЯ ФУНКЦИЯ
# =============================================================================

def create_simplified_coordinator(
    db: Session,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
) -> SimplifiedAgentCoordinator:
    """
    Создать экземпляр упрощённого координатора.
    
    Args:
        db: Database session
        rag_service: RAG service
        document_processor: Document processor
    
    Returns:
        SimplifiedAgentCoordinator instance
    """
    return SimplifiedAgentCoordinator(
        db=db,
        rag_service=rag_service,
        document_processor=document_processor,
    )

