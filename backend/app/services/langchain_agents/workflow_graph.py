"""Workflow Graph Builder - создание графа из workflow template с interrupt_before"""
from typing import Dict, Any, List, Optional
from langgraph.graph import StateGraph, END, START
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.workflow_templates import WorkflowTemplate, get_workflow_template
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.utils.checkpointer_setup import get_checkpointer_instance
from app.services.langchain_agents.store_integration import create_store_instance
import logging

logger = logging.getLogger(__name__)


def create_workflow_graph(
    template_id: str,
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> Any:
    """
    Создает LangGraph граф на основе workflow template с interrupt_before для шагов,
    требующих одобрения (requires_approval=True).
    
    Args:
        template_id: ID workflow template
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Compiled LangGraph graph с interrupt_before для шагов, требующих одобрения
    """
    # Получаем template
    template = get_workflow_template(template_id)
    
    # Создаем граф
    graph = StateGraph(AnalysisState)
    
    # Добавляем START -> first_step
    if template.steps:
        graph.add_edge(START, template.steps[0].agent)
    else:
        logger.warning(f"Template {template_id} has no steps")
        graph.add_edge(START, END)
        return graph.compile()
    
    # Импортируем узлы агентов динамически
    node_functions = _get_agent_node_functions(db, rag_service, document_processor)
    
    # Добавляем узлы и связи
    for i, step in enumerate(template.steps):
        agent_name = step.agent
        
        # Добавляем узел если его еще нет
        if agent_name not in node_functions:
            logger.warning(f"Agent {agent_name} not found, skipping step {step.name}")
            continue
        
        # Добавляем узел в граф
        graph.add_node(agent_name, node_functions[agent_name])
        
        # Добавляем связи между шагами
        if i < len(template.steps) - 1:
            # Связь к следующему шагу
            next_agent = template.steps[i + 1].agent
            graph.add_edge(agent_name, next_agent)
        else:
            # Последний шаг -> END
            graph.add_edge(agent_name, END)
    
    # Получаем checkpointer
    checkpointer = get_checkpointer_instance()
    if not checkpointer:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
    
    # Получаем store (опционально)
    store = create_store_instance()
    
    # Определяем узлы, которые требуют interrupt_before
    nodes_requiring_approval = [
        step.agent for step in template.steps if step.requires_approval
    ]
    
    # Компилируем граф с interrupt_before
    if nodes_requiring_approval:
        if store:
            compiled_graph = graph.compile(
                checkpointer=checkpointer,
                store=store,
                interrupt_before=nodes_requiring_approval
            )
        else:
            compiled_graph = graph.compile(
                checkpointer=checkpointer,
                interrupt_before=nodes_requiring_approval
            )
        logger.info(
            f"Workflow graph compiled with interrupt_before for nodes: {nodes_requiring_approval}"
        )
    else:
        if store:
            compiled_graph = graph.compile(checkpointer=checkpointer, store=store)
        else:
            compiled_graph = graph.compile(checkpointer=checkpointer)
        logger.info(f"Workflow graph compiled without interrupts (no steps require approval)")
    
    return compiled_graph


def _get_agent_node_functions(
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> Dict[str, Any]:
    """
    Получает словарь функций узлов агентов
    
    Returns:
        Dict mapping agent_name -> node_function
    """
    from app.services.langchain_agents.timeline_node import timeline_agent_node
    from app.services.langchain_agents.key_facts_node import key_facts_agent_node
    from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
    from app.services.langchain_agents.risk_node import risk_agent_node
    from app.services.langchain_agents.summary_node import summary_agent_node
    from app.services.langchain_agents.document_classifier_node import document_classifier_agent_node
    from app.services.langchain_agents.entity_extraction_node import entity_extraction_agent_node
    from app.services.langchain_agents.privilege_check_node import privilege_check_agent_node
    from app.services.langchain_agents.relationship_node import relationship_agent_node
    
    # Маппинг имен агентов из workflow templates на функции узлов
    agent_to_node = {
        "timeline": lambda state: timeline_agent_node(state, db, rag_service, document_processor),
        "key_facts": lambda state: key_facts_agent_node(state, db, rag_service, document_processor),
        "discrepancy": lambda state: discrepancy_agent_node(state, db, rag_service, document_processor),
        "risk": lambda state: risk_agent_node(state, db, rag_service, document_processor),
        "summary": lambda state: summary_agent_node(state, db, rag_service, document_processor),
        "document_classifier": lambda state: document_classifier_agent_node(state, db, rag_service, document_processor),
        "entity_extraction": lambda state: entity_extraction_agent_node(state, db, rag_service, document_processor),
        "privilege_check": lambda state: privilege_check_agent_node(state, db, rag_service, document_processor),
        "relationship": lambda state: relationship_agent_node(state, db, rag_service, document_processor),
    }
    
    return agent_to_node

