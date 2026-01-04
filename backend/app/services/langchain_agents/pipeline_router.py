"""Pipeline Router Middleware - автоматическая маршрутизация simple/complex запросов"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.complexity_classifier import ComplexityClassifier, ClassificationResult
import logging

logger = logging.getLogger(__name__)


class PipelineRouterMiddleware:
    """
    Middleware для автоматической маршрутизации запросов:
    - simple → RAG путь
    - complex → Agent путь
    
    Использует ComplexityClassifier для определения пути обработки.
    """
    
    def __init__(self, classifier: ComplexityClassifier, enable_routing: bool = True):
        """
        Инициализация PipelineRouterMiddleware
        
        Args:
            classifier: ComplexityClassifier для классификации запросов
            enable_routing: Включить автоматическую маршрутизацию
        """
        self.classifier = classifier
        self.enable_routing = enable_routing
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        """
        Вызывается перед выполнением узла
        
        Анализирует запрос пользователя и устанавливает routing_path в state
        
        Args:
            state: Текущее состояние
            node_name: Имя узла
            
        Returns:
            Обновленное состояние с routing_path
        """
        if not self.enable_routing:
            return state
        
        try:
            # Получаем последнее сообщение пользователя
            messages = state.get("messages", [])
            if not messages:
                return state
            
            # Находим последнее HumanMessage
            from langchain_core.messages import HumanMessage
            last_user_message = None
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    last_user_message = msg
                    break
            
            if not last_user_message or not hasattr(last_user_message, 'content'):
                return state
            
            user_query = last_user_message.content if isinstance(last_user_message.content, str) else str(last_user_message.content)
            
            # Классифицируем запрос
            classification = self.classifier.classify(
                query=user_query,
                context={
                    "case_id": state.get("case_id"),
                    "user_id": state.get("context").user_id if state.get("context") else None
                }
            )
            
            # Устанавливаем routing_path в state
            new_state = dict(state)
            if "metadata" not in new_state:
                new_state["metadata"] = {}
            
            new_state["metadata"]["routing_path"] = classification.recommended_path
            new_state["metadata"]["classification"] = {
                "label": classification.label,
                "confidence": classification.confidence,
                "rationale": classification.rationale
            }
            
            logger.info(
                f"[PipelineRouter] Classified query as {classification.label} "
                f"(confidence: {classification.confidence:.2f}, path: {classification.recommended_path})"
            )
            
            return new_state
            
        except Exception as e:
            logger.warning(f"[PipelineRouter] Error in routing: {e}")
            # Fallback: устанавливаем agent путь по умолчанию
            new_state = dict(state)
            if "metadata" not in new_state:
                new_state["metadata"] = {}
            new_state["metadata"]["routing_path"] = "agent"
            return new_state
    
    def after_execution(self, state: AnalysisState, node_name: str, result_state: AnalysisState) -> AnalysisState:
        """
        Вызывается после выполнения узла
        
        Args:
            state: Исходное состояние
            node_name: Имя узла
            result_state: Результирующее состояние
            
        Returns:
            Результирующее состояние
        """
        return result_state
    
    def on_error(self, state: AnalysisState, node_name: str, error: Exception) -> Optional[AnalysisState]:
        """
        Вызывается при ошибке
        
        Args:
            state: Состояние на момент ошибки
            node_name: Имя узла
            error: Произошедшая ошибка
            
        Returns:
            None (не восстанавливаем состояние)
        """
        logger.debug(f"[PipelineRouter] Error in node {node_name}: {error}")
        return None

