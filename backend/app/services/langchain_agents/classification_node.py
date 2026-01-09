"""Classification Node for LangGraph - узел классификации для графа"""
from typing import Dict, Any
from datetime import datetime
from app.services.langchain_agents.state import AnalysisState
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.utils.llm_utils import create_llm
from app.services.langchain_agents.advanced_complexity_classifier import AdvancedComplexityClassifier
import logging

logger = logging.getLogger(__name__)


def classification_node(
    state: AnalysisState,
    db: Session,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Узел классификации запросов пользователя для LangGraph
    
    Классифицирует запрос и сохраняет результат в state.metadata.classification
    Результат используется conditional edges для маршрутизации
    
    Args:
        state: Текущее состояние графа
        db: Сессия базы данных
        rag_service: RAG сервис (опционально)
        document_processor: Document processor (опционально)
        
    Returns:
        Обновленное состояние с classification в metadata
    """
    case_id = state.get("case_id", "unknown")
    
    try:
        # Инициализируем классификатор
        llm = create_llm(temperature=0.0, top_p=1.0, max_tokens=500)
        
        # Получаем кэш
        from app.routes.assistant_chat import get_classification_cache
        cache = get_classification_cache()
        
        classifier = AdvancedComplexityClassifier(
            llm=llm,
            cache=cache,
            confidence_threshold=0.7
        )
        
        # Классифицируем на основе state
        classification_result = classifier.classify_from_state(state, use_command=False)
        
        # Сохраняем в state
        new_state = dict(state)
        if "metadata" not in new_state:
            new_state["metadata"] = {}
        
        new_state["metadata"]["classification"] = classification_result.dict()
        new_state["metadata"]["classification_timestamp"] = datetime.now().isoformat()
        new_state["metadata"]["routing_path"] = classification_result.recommended_path
        
        logger.info(
            f"[ClassificationNode] {case_id}: '{classification_result.label}' "
            f"(confidence: {classification_result.confidence:.2f}, "
            f"path: {classification_result.recommended_path})"
        )
        
        return new_state
        
    except Exception as e:
        logger.error(f"[ClassificationNode] Error: {e}", exc_info=True)
        # Fallback: считаем простым вопросом
        new_state = dict(state)
        if "metadata" not in new_state:
            new_state["metadata"] = {}
        
        new_state["metadata"]["classification"] = {
            "label": "simple",
            "confidence": 0.5,
            "rationale": f"Ошибка классификации: {str(e)}",
            "recommended_path": "rag",
            "requires_clarification": False,
            "suggested_agents": [],
            "rag_queries": [],
            "estimated_complexity": "medium",
            "metadata": {}
        }
        new_state["metadata"]["routing_path"] = "rag"
        
        return new_state


def route_after_classification(state: AnalysisState) -> str:
    """
    Функция маршрутизации после классификации (для conditional edges)
    
    Использует результат классификации из state.metadata.classification
    для определения следующего узла
    
    Args:
        state: Текущее состояние графа
        
    Returns:
        Имя следующего узла: "rag_node", "supervisor", "hybrid_start", "clarification_needed"
    """
    classification = state.get("metadata", {}).get("classification", {})
    
    if not classification:
        logger.warning("[RouteAfterClassification] No classification found, defaulting to rag_node")
        return "rag_node"
    
    recommended_path = classification.get("recommended_path", "rag")
    requires_clarification = classification.get("requires_clarification", False)
    
    # Если требуется уточнение
    if requires_clarification:
        logger.info("[RouteAfterClassification] Requires clarification")
        return "clarification_needed"
    
    # Маршрутизация на основе recommended_path
    route_map = {
        "rag": "rag_node",
        "agent": "supervisor",  # Или "understand" если LEGORA workflow
        "hybrid": "hybrid_start"
    }
    
    next_node = route_map.get(recommended_path, "rag_node")
    logger.info(f"[RouteAfterClassification] Routing to: {next_node} (path: {recommended_path})")
    
    return next_node

