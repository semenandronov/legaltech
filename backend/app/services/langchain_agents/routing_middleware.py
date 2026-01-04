"""Routing Middleware - динамическая маршрутизация на основе запросов"""
from typing import Dict, Any, Optional, List
from app.services.langchain_agents.state import AnalysisState
import logging

logger = logging.getLogger(__name__)


class RoutingMiddleware:
    """
    Middleware для динамической маршрутизации на основе типа запроса
    
    Анализирует сообщения пользователя и может динамически добавлять
    подсказки или tools для улучшения работы агентов.
    """
    
    def __init__(self, enable_dynamic_routing: bool = True):
        """
        Инициализация RoutingMiddleware
        
        Args:
            enable_dynamic_routing: Включить динамическую маршрутизацию
        """
        self.enable_dynamic_routing = enable_dynamic_routing
    
    def before_execution(self, state: AnalysisState, node_name: str) -> AnalysisState:
        """
        Вызывается перед выполнением узла
        
        Может анализировать state и добавлять подсказки для улучшения маршрутизации
        
        Args:
            state: Текущее состояние
            node_name: Имя узла
            
        Returns:
            Обновленное состояние (возможно с дополнительными подсказками)
        """
        if not self.enable_dynamic_routing:
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
            
            # Анализируем запрос и можем добавить подсказки в metadata
            routing_hints = self._analyze_query(user_query)
            
            if routing_hints:
                new_state = dict(state)
                if "metadata" not in new_state:
                    new_state["metadata"] = {}
                new_state["metadata"]["routing_hints"] = routing_hints
                logger.debug(f"[RoutingMiddleware] Added routing hints for node {node_name}: {routing_hints}")
                return new_state
            
            return state
            
        except Exception as e:
            logger.warning(f"[RoutingMiddleware] Error in routing analysis: {e}")
            return state
    
    def _analyze_query(self, query: str) -> Dict[str, Any]:
        """
        Анализировать запрос пользователя и вернуть подсказки для маршрутизации
        
        Args:
            query: Запрос пользователя
            
        Returns:
            Словарь с подсказками для маршрутизации
        """
        if not query:
            return {}
        
        query_lower = query.lower()
        hints = {}
        
        # Обнаруживаем запросы на поиск документов
        if any(keyword in query_lower for keyword in ['найди', 'найти', 'поиск', 'ищи', 'документ', 'файл']):
            hints["suggest_tool"] = "retrieve_documents"
            hints["priority"] = "high"
        
        # Обнаруживаем запросы на анализ
        if any(keyword in query_lower for keyword in ['анализ', 'проанализируй', 'риски', 'противоречия']):
            hints["suggest_agent"] = "risk" if "риск" in query_lower else "discrepancy"
            hints["priority"] = "high"
        
        # Обнаруживаем простые вопросы (для будущей маршрутизации RAG vs Agent)
        simple_question_keywords = ['что', 'когда', 'где', 'кто', 'сколько', 'какой']
        if any(keyword in query_lower for keyword in simple_question_keywords) and len(query.split()) < 10:
            hints["complexity"] = "simple"
            hints["suggest_path"] = "rag"
        else:
            hints["complexity"] = "complex"
            hints["suggest_path"] = "agent"
        
        return hints
    
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
        # Можно добавить логику для адаптации маршрутизации на основе результатов
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
        logger.debug(f"[RoutingMiddleware] Error in node {node_name}: {error}")
        return None

