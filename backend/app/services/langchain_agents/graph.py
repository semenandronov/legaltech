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
from app.services.langchain_agents.document_classifier_node import document_classifier_agent_node
from app.services.langchain_agents.entity_extraction_node import entity_extraction_agent_node
from app.services.langchain_agents.privilege_check_node import privilege_check_agent_node
from app.services.langchain_agents.relationship_node import relationship_agent_node
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
    
    def document_classifier_node(state: AnalysisState) -> AnalysisState:
        return document_classifier_agent_node(state, db, rag_service, document_processor)
    
    def entity_extraction_node(state: AnalysisState) -> AnalysisState:
        return entity_extraction_agent_node(state, db, rag_service, document_processor)
    
    def privilege_check_node(state: AnalysisState) -> AnalysisState:
        return privilege_check_agent_node(state, db, rag_service, document_processor)
    
    def relationship_node(state: AnalysisState) -> AnalysisState:
        return relationship_agent_node(state, db, rag_service, document_processor)
    
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
    graph.add_node("document_classifier", document_classifier_node)
    graph.add_node("entity_extraction", entity_extraction_node)
    graph.add_node("privilege_check", privilege_check_node)
    graph.add_node("relationship", relationship_node)
    
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
            "document_classifier": "document_classifier",
            "entity_extraction": "entity_extraction",
            "privilege_check": "privilege_check",
            "relationship": "relationship",
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
    graph.add_edge("document_classifier", "supervisor")
    graph.add_edge("entity_extraction", "supervisor")
    graph.add_edge("privilege_check", "supervisor")
    graph.add_edge("relationship", "supervisor")
    
    # Compile graph with checkpointer
    # NOTE: PostgresSaver.from_conn_string() returns a context manager in newer versions
    # Using MemorySaver for now to avoid context manager issues
    # TODO: Fix PostgresSaver integration when langgraph API stabilizes
    checkpointer = MemorySaver()
    logger.info("✅ Using MemorySaver for state persistence (PostgresSaver temporarily disabled)")
    
    # Alternative: Try PostgresSaver if needed (commented out due to context manager issues)
    # try:
    #     from langgraph.checkpoint.postgres import PostgresSaver
    #     from app.config import config
    #     
    #     db_url = config.DATABASE_URL
    #     if db_url.startswith("postgresql+psycopg://"):
    #         db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
    #     
    #     # PostgresSaver.from_conn_string() may return a context manager
    #     # This needs to be handled properly with async context manager
    #     checkpointer = PostgresSaver.from_conn_string(db_url)
    #     logger.info("✅ Using PostgreSQL checkpointer for state persistence")
    # except (ImportError, Exception) as e:
    #     logger.warning(f"PostgresSaver not available ({e}), using MemorySaver")
    #     checkpointer = MemorySaver()
    
    compiled_graph = graph.compile(checkpointer=checkpointer)
    
    logger.info("Created LangGraph for multi-agent analysis")
    
    return compiled_graph
