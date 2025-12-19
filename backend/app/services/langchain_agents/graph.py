"""LangGraph graph for multi-agent analysis system"""
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from app.services.langchain_agents.state import AnalysisState
from app.config import config
from app.services.langchain_agents.supervisor import route_to_agent, create_supervisor_agent
from app.services.langchain_agents.timeline_node import timeline_agent_node
from app.services.langchain_agents.key_facts_node import key_facts_agent_node
from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
from app.services.langchain_agents.risk_node import risk_agent_node
from app.services.langchain_agents.summary_node import summary_agent_node
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
import logging

logger = logging.getLogger(__name__)


def create_analysis_graph(
    db: Session = None,
    rag_service: RAGService = None,
    document_processor: DocumentProcessor = None
) -> StateGraph:
    """
    Create LangGraph for multi-agent analysis
    
    Args:
        db: Database session
        rag_service: RAG service instance
        document_processor: Document processor instance
    
    Returns:
        Compiled LangGraph graph
    """
    # Create wrapper functions that pass db and services
    def timeline_node(state: AnalysisState) -> AnalysisState:
        return timeline_agent_node(state, db, rag_service, document_processor)
    
    def key_facts_node(state: AnalysisState) -> AnalysisState:
        return key_facts_agent_node(state, db, rag_service, document_processor)
    
    def discrepancy_node(state: AnalysisState) -> AnalysisState:
        return discrepancy_agent_node(state, db, rag_service, document_processor)
    
    def risk_node(state: AnalysisState) -> AnalysisState:
        return risk_agent_node(state, db, rag_service, document_processor)
    
    def summary_node(state: AnalysisState) -> AnalysisState:
        return summary_agent_node(state, db, rag_service, document_processor)
    
    def supervisor_node(state: AnalysisState) -> AnalysisState:
        """Supervisor node - routes to appropriate agent"""
        # Supervisor doesn't modify state, just routes
        return state
    
    # Create the graph
    graph = StateGraph(AnalysisState)
    
    # Add nodes
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("timeline", timeline_node)
    graph.add_node("key_facts", key_facts_node)
    graph.add_node("discrepancy", discrepancy_node)
    graph.add_node("risk", risk_node)
    graph.add_node("summary", summary_node)
    
    # Add edges from START
    graph.add_edge(START, "supervisor")
    
    # Add conditional edges from supervisor
    graph.add_conditional_edges(
        "supervisor",
        route_to_agent,
        {
            "timeline": "timeline",
            "key_facts": "key_facts",
            "discrepancy": "discrepancy",
            "risk": "risk",
            "summary": "summary",
            "end": END,
            "supervisor": "supervisor"  # Wait if dependencies not ready
        }
    )
    
    # All agent nodes return to supervisor
    graph.add_edge("timeline", "supervisor")
    graph.add_edge("key_facts", "supervisor")
    graph.add_edge("discrepancy", "supervisor")
    graph.add_edge("risk", "supervisor")
    graph.add_edge("summary", "supervisor")
    
    # Compile graph with checkpointer
    # Try PostgreSQL checkpointer, fallback to MemorySaver
    checkpointer = None
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        # PostgresSaver.from_conn_string returns a context manager, we need to use it properly
        # For now, use MemorySaver as it's more reliable
        # TODO: Fix PostgresSaver usage when LangGraph API is stable
        logger.warning(
            "PostgreSQL checkpointer temporarily disabled due to API changes. "
            "Using MemorySaver. State will not persist across restarts."
        )
        checkpointer = MemorySaver()
    except Exception as e:
        logger.warning(
            f"PostgreSQL checkpointer unavailable ({e}), "
            "using MemorySaver. State will not persist across restarts."
        )
        checkpointer = MemorySaver()
    
    if checkpointer is None:
        checkpointer = MemorySaver()
    
    compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info("Created LangGraph for multi-agent analysis")
    
    return compiled_graph
