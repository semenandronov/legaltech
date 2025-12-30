"""PLAN node for LEGORA workflow - Phase 2: Creating analysis plan based on understanding"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.planning_agent import PlanningAgent
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)


def plan_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    ФАЗА 2: PLAN - создание плана на основе понимания задачи
    
    Использует understanding_result из UNDERSTAND фазы для создания
    детального плана анализа с шагами, зависимостями и reasoning.
    
    Args:
        state: Current analysis state (должен содержать understanding_result)
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with current_plan
    """
    case_id = state.get("case_id")
    understanding_result = state.get("understanding_result")
    
    # Проверяем, есть ли понимание задачи
    if not understanding_result:
        logger.warning(f"[PLAN] No understanding_result found for case {case_id}, creating fallback plan")
        # Создаем простой план на основе analysis_types
        analysis_types = state.get("analysis_types", [])
        state["current_plan"] = {
            "analysis_types": analysis_types,
            "steps": [{"agent_name": at, "step_id": f"{at}_step"} for at in analysis_types],
            "reasoning": "Fallback plan created without understanding phase",
            "confidence": 0.5
        }
        return state
    
    # Проверяем, нужен ли план (для простых задач можно пропустить)
    needs_planning = understanding_result.get("needs_planning", True)
    if not needs_planning:
        logger.info(f"[PLAN] Task is simple, creating minimal plan")
        # Для простых задач создаем минимальный план
        suggested_analyses = understanding_result.get("suggested_analyses", [])
        if not suggested_analyses:
            # Используем analysis_types из state
            suggested_analyses = state.get("analysis_types", [])
        
        state["current_plan"] = {
            "analysis_types": suggested_analyses,
            "steps": [{"agent_name": at, "step_id": f"{at}_step"} for at in suggested_analyses],
            "reasoning": "Simple plan for straightforward task",
            "confidence": 0.9
        }
        return state
    
    try:
        logger.info(f"[PLAN] Creating analysis plan for case {case_id}")
        
        # Извлекаем информацию из understanding_result
        user_task = understanding_result.get("original_task", "")
        document_analysis = understanding_result.get("document_analysis")
        goals = understanding_result.get("goals", [])
        complexity = understanding_result.get("complexity", "medium")
        
        # Инициализируем PlanningAgent
        planning_agent = PlanningAgent(rag_service=rag_service, document_processor=document_processor)
        
        # Создаем план через PlanningAgent
        # PlanningAgent уже имеет логику для работы с document_analysis
        plan = planning_agent.plan_analysis(
            user_task=user_task,
            case_id=case_id,
            db=db
        )
        
        # Обогащаем план информацией из understanding_result
        if goals:
            plan["goals"] = goals
        
        # Добавляем информацию о сложности
        plan["complexity"] = complexity
        plan["task_type"] = understanding_result.get("task_type", "general")
        
        # Сохраняем план в state
        state["current_plan"] = plan
        
        # Сохраняем план в файл (DeepAgents pattern - write_todos)
        try:
            from app.services.langchain_agents.file_system_helper import get_file_system_context_from_state
            file_system_context = get_file_system_context_from_state(state)
            if file_system_context:
                file_system_context.write_result("plan.json", plan, subdirectory="")
        except Exception as fs_error:
            logger.debug(f"Failed to save plan to file: {fs_error}")
        
        # Также сохраняем analysis_types для обратной совместимости
        if "analysis_types" in plan:
            state["analysis_types"] = plan["analysis_types"]
        
        # Сохраняем plan_goals для адаптивной системы
        if "goals" in plan:
            from app.services.langchain_agents.state import PlanGoal
            plan_goals = []
            for goal_data in plan["goals"]:
                if isinstance(goal_data, dict):
                    plan_goals.append(goal_data)
                elif isinstance(goal_data, str):
                    # Преобразуем строку в структуру PlanGoal
                    plan_goals.append({
                        "goal_id": f"goal_{len(plan_goals) + 1}",
                        "description": goal_data,
                        "priority": len(plan_goals) + 1
                    })
            state["plan_goals"] = plan_goals
        
        # Сохраняем steps для адаптивной системы
        if "steps" in plan:
            state["current_plan"] = plan  # current_plan уже содержит steps
        
        logger.info(
            f"[PLAN] Plan created: {len(plan.get('analysis_types', []))} analysis types, "
            f"{len(plan.get('steps', []))} steps, confidence: {plan.get('confidence', 0.8):.2f}"
        )
        
        return state
        
    except Exception as e:
        logger.error(f"[PLAN] Error creating plan for case {case_id}: {e}", exc_info=True)
        
        # Fallback: создаем простой план на основе understanding_result
        suggested_analyses = understanding_result.get("suggested_analyses", [])
        if not suggested_analyses:
            suggested_analyses = state.get("analysis_types", ["timeline", "key_facts"])
        
        state["current_plan"] = {
            "analysis_types": suggested_analyses,
            "steps": [{"agent_name": at, "step_id": f"{at}_step"} for at in suggested_analyses],
            "reasoning": f"Fallback plan created due to error: {str(e)}",
            "confidence": 0.6
        }
        state["analysis_types"] = suggested_analyses
        
        return state

