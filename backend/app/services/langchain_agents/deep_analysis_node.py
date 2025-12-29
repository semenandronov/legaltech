"""Deep Analysis Node for complex multi-step analysis tasks"""
from typing import Dict, Any
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.deep_reasoning_agent import DeepReasoningAgent
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)


def deep_analysis_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    Узел для сложного многошагового анализа
    
    Используется вместо обычных агентов для сложных задач, которые требуют:
    - Многошагового reasoning
    - Синтеза результатов из разных источников
    - Глубокого анализа с объяснением
    
    Определяет сложность из understanding_result и использует DeepReasoningAgent
    если задача сложная.
    
    Args:
        state: Current analysis state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with deep_analysis_result
    """
    case_id = state.get("case_id")
    understanding_result = state.get("understanding_result", {})
    
    try:
        logger.info(f"[DeepAnalysis] Starting deep analysis for case {case_id}")
        
        # Проверяем сложность задачи
        complexity = understanding_result.get("complexity", "medium")
        task_type = understanding_result.get("task_type", "general")
        
        # Определяем, нужен ли deep analysis
        needs_deep_analysis = (
            complexity == "high" or
            task_type in ["research", "analysis", "comparison"] or
            understanding_result.get("needs_planning", False)
        )
        
        if not needs_deep_analysis:
            logger.info(f"[DeepAnalysis] Task complexity is {complexity}, skipping deep analysis")
            state["deep_analysis_result"] = {
                "status": "skipped",
                "reason": f"Task complexity ({complexity}) does not require deep analysis"
            }
            return state
        
        # Извлекаем вопрос из understanding_result
        original_task = understanding_result.get("original_task", "")
        if not original_task:
            logger.warning("[DeepAnalysis] No original_task in understanding_result")
            state["deep_analysis_result"] = {
                "status": "failed",
                "error": "No task provided"
            }
            return state
        
        # Собираем контекст из результатов других агентов
        context = {
            "timeline_result": state.get("timeline_result"),
            "key_facts_result": state.get("key_facts_result"),
            "discrepancy_result": state.get("discrepancy_result"),
            "risk_result": state.get("risk_result"),
            "entities_result": state.get("entities_result")
        }
        
        # Инициализируем DeepReasoningAgent
        deep_agent = DeepReasoningAgent(max_depth=5)
        
        # Выполняем глубокий анализ
        result = deep_agent.analyze_complex_issue(
            question=original_task,
            context=context,
            case_id=case_id
        )
        
        # Сохраняем результат
        state["deep_analysis_result"] = result
        
        logger.info(
            f"[DeepAnalysis] Deep analysis completed: status={result.get('status')}, "
            f"reasoning_steps={len(result.get('reasoning_trace', []))}"
        )
        
        return state
        
    except Exception as e:
        logger.error(f"[DeepAnalysis] Error in deep analysis for case {case_id}: {e}", exc_info=True)
        state["deep_analysis_result"] = {
            "status": "failed",
            "error": str(e)
        }
        return state

