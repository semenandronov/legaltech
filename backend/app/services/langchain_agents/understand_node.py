"""UNDERSTAND node for LEGORA workflow - Phase 1: Understanding user task"""
from typing import Dict, Any, Optional
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.planning_agent import PlanningAgent
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)


def understand_node(
    state: AnalysisState,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> AnalysisState:
    """
    ФАЗА 1: UNDERSTAND - парсинг и анализ запроса пользователя
    Выделяет явную фазу понимания задачи
    
    Анализирует:
    - Что пользователь хочет получить
    - Тип задачи (простая/сложная)
    - Контекст дела (тип дела, количество документов)
    - Ключевые индикаторы из документов
    
    Args:
        state: Current analysis state
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Updated state with understanding_result
    """
    case_id = state.get("case_id")
    user_task = state.get("metadata", {}).get("user_task") or state.get("messages", [])
    
    # Извлечь user_task из messages если нужно
    if isinstance(user_task, list) and user_task:
        # Попытаться найти user_task в последнем HumanMessage
        from langchain_core.messages import HumanMessage
        for msg in reversed(user_task):
            if isinstance(msg, HumanMessage):
                user_task = msg.content if hasattr(msg, 'content') else str(msg)
                break
        else:
            user_task = str(user_task[-1]) if user_task else ""
    
    if not user_task or not isinstance(user_task, str):
        logger.warning(f"No user_task found in state for case {case_id}")
        state["understanding_result"] = {
            "task_understood": False,
            "error": "No user task provided",
            "complexity": "unknown",
            "task_type": "unknown"
        }
        return state
    
    try:
        logger.info(f"[UNDERSTAND] Analyzing task for case {case_id}: {user_task[:100]}...")
        
        # Инициализируем PlanningAgent для анализа документов
        planning_agent = PlanningAgent(rag_service=rag_service, document_processor=document_processor)
        
        # ШАГ 1: Автономный анализ документов для понимания контекста
        document_analysis = None
        if rag_service and document_processor:
            try:
                document_analysis = planning_agent.analyze_documents_for_planning(case_id, user_task)
                logger.info(f"[UNDERSTAND] Document analysis: case_type={document_analysis.get('case_type')}")
            except Exception as e:
                logger.warning(f"[UNDERSTAND] Document analysis failed: {e}")
        
        # ШАГ 2: Анализ задачи пользователя
        # Определяем сложность задачи
        complexity = _determine_task_complexity(user_task, document_analysis)
        
        # Определяем тип задачи
        task_type = _determine_task_type(user_task)
        
        # Извлекаем ключевые цели из задачи
        goals = _extract_goals(user_task)
        
        # Определяем, нужен ли план (для простых задач можно пропустить)
        needs_planning = complexity in ["medium", "high"] or len(goals) > 1
        
        # Формируем результат понимания
        understanding_result = {
            "task_understood": True,
            "original_task": user_task,
            "complexity": complexity,  # "simple", "medium", "high"
            "task_type": task_type,  # "extraction", "analysis", "comparison", "research"
            "goals": goals,  # Список высокоуровневых целей
            "needs_planning": needs_planning,
            "document_analysis": document_analysis,
            "key_indicators": document_analysis.get("key_indicators", []) if document_analysis else [],
            "suggested_analyses": document_analysis.get("suggested_analyses", []) if document_analysis else [],
            "reasoning": _generate_understanding_reasoning(user_task, complexity, task_type, goals, document_analysis)
        }
        
        state["understanding_result"] = understanding_result
        
        # Сохраняем в файл (DeepAgents pattern)
        try:
            from app.services.langchain_agents.file_system_helper import get_file_system_context_from_state
            file_system_context = get_file_system_context_from_state(state)
            if file_system_context:
                file_system_context.write_result("understanding.json", understanding_result, subdirectory="")
        except Exception as fs_error:
            logger.debug(f"Failed to save understanding result to file: {fs_error}")
        
        # Добавить в metadata для обратной совместимости
        if "metadata" not in state:
            state["metadata"] = {}
        state["metadata"]["user_task"] = user_task
        state["metadata"]["task_complexity"] = complexity
        
        logger.info(f"[UNDERSTAND] Task understood: complexity={complexity}, type={task_type}, goals={len(goals)}, needs_planning={needs_planning}")
        
        return state
        
    except Exception as e:
        logger.error(f"[UNDERSTAND] Error understanding task for case {case_id}: {e}", exc_info=True)
        state["understanding_result"] = {
            "task_understood": False,
            "error": str(e),
            "complexity": "unknown",
            "task_type": "unknown",
            "needs_planning": True  # По умолчанию нужен план при ошибке
        }
        return state


def _determine_task_complexity(user_task: str, document_analysis: Optional[Dict[str, Any]] = None) -> str:
    """
    Определяет сложность задачи
    
    Returns:
        "simple", "medium", or "high"
    """
    task_lower = user_task.lower()
    
    # Индикаторы сложных задач
    complex_indicators = [
        "прецедент", "case law", "суд", "практика", "ВАС",
        "сравни", "сравнение", "анализ рисков", "комплексный",
        "многошаговый", "детальный", "глубокий"
    ]
    
    # Индикаторы простых задач
    simple_indicators = [
        "извлеки", "найди", "покажи", "выведи", "список",
        "даты", "суммы", "имена"
    ]
    
    complex_count = sum(1 for indicator in complex_indicators if indicator in task_lower)
    simple_count = sum(1 for indicator in simple_indicators if indicator in task_lower)
    
    # Учитываем количество документов
    file_count = 0
    if document_analysis:
        file_count = document_analysis.get("document_structure", {}).get("file_count", 0)
    
    # Определяем сложность
    if complex_count >= 2 or file_count > 20:
        return "high"
    elif complex_count >= 1 or file_count > 10:
        return "medium"
    elif simple_count >= 2:
        return "simple"
    else:
        return "medium"  # По умолчанию средняя


def _determine_task_type(user_task: str) -> str:
    """
    Определяет тип задачи
    
    Returns:
        "extraction", "analysis", "comparison", "research", or "general"
    """
    task_lower = user_task.lower()
    
    if any(word in task_lower for word in ["извлеки", "найди", "выведи", "покажи", "список"]):
        return "extraction"
    elif any(word in task_lower for word in ["проанализируй", "анализ", "риск", "оцени"]):
        return "analysis"
    elif any(word in task_lower for word in ["сравни", "сравнение", "противопоставь"]):
        return "comparison"
    elif any(word in task_lower for word in ["прецедент", "case law", "суд", "практика", "ВАС"]):
        return "research"
    else:
        return "general"


def _extract_goals(user_task: str) -> list:
    """
    Извлекает высокоуровневые цели из задачи пользователя
    
    Returns:
        Список целей (строки)
    """
    goals = []
    task_lower = user_task.lower()
    
    # Маппинг ключевых слов к целям
    goal_mapping = {
        "риск": "найти риски",
        "противоречи": "найти противоречия",
        "даты": "извлечь хронологию",
        "факты": "извлечь ключевые факты",
        "сущности": "извлечь сущности",
        "связи": "построить граф связей",
        "резюме": "создать резюме",
        "классификац": "классифицировать документы",
        "привилеги": "проверить привилегии"
    }
    
    for keyword, goal in goal_mapping.items():
        if keyword in task_lower:
            if goal not in goals:
                goals.append(goal)
    
    # Если целей не найдено, создаем общую цель
    if not goals:
        goals.append("выполнить анализ документов")
    
    return goals


def _generate_understanding_reasoning(
    user_task: str,
    complexity: str,
    task_type: str,
    goals: list,
    document_analysis: Optional[Dict[str, Any]]
) -> str:
    """
    Генерирует объяснение понимания задачи
    """
    reasoning_parts = []
    
    reasoning_parts.append(f"Задача пользователя: {user_task[:200]}")
    reasoning_parts.append(f"Тип задачи: {task_type}")
    reasoning_parts.append(f"Сложность: {complexity}")
    reasoning_parts.append(f"Цели: {', '.join(goals)}")
    
    if document_analysis:
        case_type = document_analysis.get("case_type", "unknown")
        file_count = document_analysis.get("document_structure", {}).get("file_count", 0)
        reasoning_parts.append(f"Контекст дела: тип={case_type}, документов={file_count}")
    
    return "\n".join(reasoning_parts)

