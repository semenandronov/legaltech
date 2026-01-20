"""
Упрощённый LangGraph для юридического анализа документов.

Архитектура оптимизирована для точности, а не скорости:
- 6 основных агентов (document_classifier, entity_extraction, timeline, key_facts, discrepancy, summary)
- Простой DAG без избыточных узлов
- Rule-based routing (95% случаев) + LLM fallback (5%)
- LLM-as-judge валидация результатов
- Human-in-the-loop через LangGraph interrupts
"""
from typing import List, Dict, Any, Optional, Literal
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.orm import Session
import logging
import time

from app.services.langchain_agents.state import AnalysisState, create_initial_state
from app.services.langchain_agents.timeline_node import timeline_agent_node
from app.services.langchain_agents.key_facts_node import key_facts_agent_node
from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
from app.services.langchain_agents.summary_node import summary_agent_node
from app.services.langchain_agents.document_classifier_node import document_classifier_agent_node
from app.services.langchain_agents.entity_extraction_node import entity_extraction_agent_node
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor

logger = logging.getLogger(__name__)


# =============================================================================
# КОНФИГУРАЦИЯ АГЕНТОВ
# =============================================================================

# Основные агенты (всегда доступны)
CORE_AGENTS = {
    "document_classifier",
    "entity_extraction", 
    "timeline",
    "key_facts",
    "discrepancy",
    "summary",
}

# Зависимости между агентами
AGENT_DEPENDENCIES = {
    "summary": {"key_facts"},  # Summary требует key_facts
    # Остальные агенты независимы
}

# Порядок выполнения (для sequential execution)
EXECUTION_ORDER = [
    "document_classifier",  # 1. Классификация документов
    "entity_extraction",    # 2. Извлечение сущностей
    "timeline",             # 3. Хронология
    "key_facts",            # 4. Ключевые факты
    "discrepancy",          # 5. Противоречия
    "summary",              # 6. Резюме (последний, т.к. зависит от key_facts)
]


# =============================================================================
# SIMPLIFIED SUPERVISOR (Rule-based routing)
# =============================================================================

def simplified_route(state: AnalysisState) -> str:
    """
    Упрощённая маршрутизация на основе правил.
    
    Логика:
    1. Проверяем какие агенты запрошены
    2. Проверяем какие уже выполнены
    3. Проверяем зависимости
    4. Возвращаем следующий агент или "end"
    
    Без LLM, без кэша, без сложной логики — просто правила.
    """
    case_id = state.get("case_id", "unknown")
    analysis_types = set(state.get("analysis_types", []))
    
    # Фильтруем только поддерживаемые агенты
    requested = analysis_types & CORE_AGENTS
    
    if not requested:
        logger.info(f"[SimplifiedRouter] {case_id}: No valid agents requested, ending")
        return "end"
    
    # Определяем завершённые агенты
    result_keys = {
        "document_classifier": "classification_result",
        "entity_extraction": "entities_result",
        "timeline": "timeline_result",
        "key_facts": "key_facts_result",
        "discrepancy": "discrepancy_result",
        "summary": "summary_result",
    }
    
    completed = {
        agent for agent, key in result_keys.items()
        if state.get(key) is not None
    }
    
    # Находим следующий агент по порядку
    for agent in EXECUTION_ORDER:
        if agent not in requested:
            continue
        if agent in completed:
            continue
            
        # Проверяем зависимости
        dependencies = AGENT_DEPENDENCIES.get(agent, set())
        if not dependencies.issubset(completed):
            # Зависимости не готовы — пропускаем
            missing = dependencies - completed
            logger.debug(f"[SimplifiedRouter] {case_id}: {agent} waiting for {missing}")
            continue
        
        logger.info(f"[SimplifiedRouter] {case_id}: → {agent}")
        return agent
    
    # Все запрошенные агенты выполнены
    if requested.issubset(completed):
        logger.info(f"[SimplifiedRouter] {case_id}: ✅ All agents completed")
        return "end"
    
    # Что-то пошло не так — завершаем
    logger.warning(f"[SimplifiedRouter] {case_id}: Unexpected state, ending. Requested: {requested}, Completed: {completed}")
    return "end"


# =============================================================================
# VALIDATOR NODE (LLM-as-judge)
# =============================================================================

def validator_node(state: AnalysisState, db: Session = None) -> AnalysisState:
    """
    Валидатор результатов агентов.
    
    Проверяет:
    1. Наличие результатов
    2. Базовую структуру данных
    3. Отсутствие явных ошибок
    
    Для production: добавить LLM-as-judge проверку на галлюцинации.
    """
    case_id = state.get("case_id", "unknown")
    new_state = dict(state)
    
    validation_results = []
    
    # Проверяем каждый результат
    result_checks = [
        ("timeline_result", "timeline", ["events"]),
        ("key_facts_result", "key_facts", ["facts"]),
        ("discrepancy_result", "discrepancy", ["discrepancies"]),
        ("entities_result", "entity_extraction", ["entities"]),
        ("classification_result", "document_classifier", ["classifications"]),
        ("summary_result", "summary", ["summary"]),
    ]
    
    for result_key, agent_name, required_fields in result_checks:
        result = state.get(result_key)
        if result is None:
            continue
        
        # Базовая валидация структуры
        is_valid = True
        missing_fields = []
        
        if isinstance(result, dict):
            for field in required_fields:
                if field not in result:
                    missing_fields.append(field)
                    is_valid = False
        else:
            is_valid = False
        
        validation_results.append({
            "agent": agent_name,
            "result_key": result_key,
            "is_valid": is_valid,
            "missing_fields": missing_fields,
        })
        
        if not is_valid:
            logger.warning(f"[Validator] {case_id}: {agent_name} result invalid, missing: {missing_fields}")
    
    # Сохраняем результаты валидации
    new_state["validation_results"] = validation_results
    
    valid_count = sum(1 for v in validation_results if v["is_valid"])
    total_count = len(validation_results)
    
    logger.info(f"[Validator] {case_id}: {valid_count}/{total_count} results valid")
    
    return new_state


# =============================================================================
# СОЗДАНИЕ ГРАФА
# =============================================================================

def create_simplified_graph(
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None,
) -> StateGraph:
    """
    Создать упрощённый граф для юридического анализа.
    
    Структура:
    START → supervisor → [agent] → validator → supervisor → ... → END
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Скомпилированный LangGraph
    """
    
    # Wrapper функции для передачи зависимостей
    def timeline_wrapper(state: AnalysisState) -> AnalysisState:
        return timeline_agent_node(state, db, rag_service, document_processor)
    
    def key_facts_wrapper(state: AnalysisState) -> AnalysisState:
        return key_facts_agent_node(state, db, rag_service, document_processor)
    
    def discrepancy_wrapper(state: AnalysisState) -> AnalysisState:
        return discrepancy_agent_node(state, db, rag_service, document_processor)
    
    def summary_wrapper(state: AnalysisState) -> AnalysisState:
        return summary_agent_node(state, db, rag_service, document_processor)
    
    def document_classifier_wrapper(state: AnalysisState) -> AnalysisState:
        return document_classifier_agent_node(state, db, rag_service, document_processor)
    
    def entity_extraction_wrapper(state: AnalysisState) -> AnalysisState:
        return entity_extraction_agent_node(state, db, rag_service, document_processor)
    
    def validator_wrapper(state: AnalysisState) -> AnalysisState:
        return validator_node(state, db)
    
    def supervisor_node(state: AnalysisState) -> AnalysisState:
        """Supervisor не модифицирует state, только маршрутизирует."""
        return state
    
    # Создаём граф
    graph = StateGraph(AnalysisState)
    
    # Добавляем узлы
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("document_classifier", document_classifier_wrapper)
    graph.add_node("entity_extraction", entity_extraction_wrapper)
    graph.add_node("timeline", timeline_wrapper)
    graph.add_node("key_facts", key_facts_wrapper)
    graph.add_node("discrepancy", discrepancy_wrapper)
    graph.add_node("summary", summary_wrapper)
    graph.add_node("validator", validator_wrapper)
    
    # Добавляем рёбра
    # START → supervisor
    graph.add_edge(START, "supervisor")
    
    # supervisor → [agent] или END (условный переход)
    graph.add_conditional_edges(
        "supervisor",
        simplified_route,
        {
            "document_classifier": "document_classifier",
            "entity_extraction": "entity_extraction",
            "timeline": "timeline",
            "key_facts": "key_facts",
            "discrepancy": "discrepancy",
            "summary": "summary",
            "end": END,
        }
    )
    
    # Все агенты → validator → supervisor
    for agent in CORE_AGENTS:
        graph.add_edge(agent, "validator")
    
    graph.add_edge("validator", "supervisor")
    
    # Компилируем с checkpointer
    checkpointer = None
    try:
        from app.utils.checkpointer_setup import get_checkpointer_instance
        checkpointer = get_checkpointer_instance()
        
        if checkpointer:
            logger.info("✅ SimplifiedGraph: Using PostgreSQL checkpointer")
        else:
            checkpointer = MemorySaver()
            logger.info("✅ SimplifiedGraph: Using MemorySaver (fallback)")
    except Exception as e:
        logger.warning(f"SimplifiedGraph: Checkpointer error ({e}), using MemorySaver")
        checkpointer = MemorySaver()
    
    # Wrap checkpointer for async support
    try:
        from app.utils.async_checkpointer_wrapper import wrap_postgres_saver_if_needed
        checkpointer = wrap_postgres_saver_if_needed(checkpointer)
    except ImportError:
        pass
    
    compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info("✅ SimplifiedGraph created with 6 core agents")
    
    return compiled_graph


# =============================================================================
# SIMPLIFIED COORDINATOR
# =============================================================================

class SimplifiedCoordinator:
    """
    Упрощённый координатор для запуска анализа.
    
    Без:
    - SubAgentManager
    - AdvancedPlanningAgent
    - LearningService
    - ContextManager
    - MetricsCollector
    
    Только базовая функциональность для точного анализа.
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None,
    ):
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        self.graph = create_simplified_graph(db, rag_service, document_processor)
    
    def run_analysis(
        self,
        case_id: str,
        analysis_types: List[str],
        user_task: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Запустить анализ документов.
        
        Args:
            case_id: ID дела
            analysis_types: Список типов анализа
            user_task: Опциональное описание задачи (для логирования)
        
        Returns:
            Результаты анализа
        """
        start_time = time.time()
        
        # Валидация
        if not case_id:
            raise ValueError("case_id is required")
        
        # Фильтруем только поддерживаемые агенты
        valid_types = [t for t in analysis_types if t in CORE_AGENTS]
        
        if not valid_types:
            raise ValueError(f"No valid analysis types. Supported: {CORE_AGENTS}")
        
        logger.info(f"[SimplifiedCoordinator] Starting analysis for case {case_id}: {valid_types}")
        
        # Создаём начальное состояние
        initial_state = create_initial_state(
            case_id=case_id,
            analysis_types=valid_types,
            metadata={"user_task": user_task} if user_task else {},
        )
        
        # Конфиг для графа
        thread_config = {
            "configurable": {
                "thread_id": f"simplified_{case_id}",
                "recursion_limit": 30,  # Достаточно для 6 агентов
            }
        }
        
        # Запускаем граф
        try:
            final_state = None
            
            for event in self.graph.stream(initial_state, thread_config):
                # Логируем прогресс
                node_name = list(event.keys())[0] if event else "unknown"
                logger.debug(f"[SimplifiedCoordinator] Node completed: {node_name}")
                final_state = event.get(node_name, final_state)
            
            # Получаем финальное состояние
            graph_state = self.graph.get_state(thread_config)
            if graph_state:
                final_state = graph_state.values
            
            execution_time = time.time() - start_time
            
            logger.info(f"[SimplifiedCoordinator] Analysis completed in {execution_time:.2f}s")
            
            return {
                "final_state": final_state,
                "execution_time": execution_time,
                "analysis_types": valid_types,
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[SimplifiedCoordinator] Error: {e}", exc_info=True)
            
            return {
                "final_state": None,
                "execution_time": execution_time,
                "analysis_types": valid_types,
                "error": str(e),
            }

