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
from app.services.langchain_agents.evaluation_node import evaluation_node
from app.services.langchain_agents.adaptation_engine import adaptation_node
from app.services.langchain_agents.human_feedback import get_feedback_service
from sqlalchemy.orm import Session
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    
    def evaluation_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for evaluation node with services"""
        return evaluation_node(state, db, rag_service, document_processor)
    
    def adaptation_wrapper(state: AnalysisState) -> AnalysisState:
        """Wrapper for adaptation node with services"""
        return adaptation_node(state, db, rag_service, document_processor)
    
    def human_feedback_wait_node(state: AnalysisState) -> AnalysisState:
        """
        Human feedback wait node - checks if feedback has been received.
        If feedback received, integrates it into state for agent retry.
        If not, returns to supervisor to wait.
        Has timeout to prevent infinite loops.
        """
        case_id = state.get("case_id", "unknown")
        current_request = state.get("current_feedback_request")
        feedback_responses = state.get("feedback_responses", {})
        
        if not current_request:
            logger.warning(f"[HumanFeedback] No current feedback request for case {case_id}")
            new_state = dict(state)
            new_state["waiting_for_human"] = False
            return new_state
        
        request_id = current_request.get("request_id")
        
        # Check if response received
        if request_id in feedback_responses:
            response = feedback_responses[request_id]
            logger.info(f"[HumanFeedback] Response received for request {request_id}: {response[:100]}")
            
            # Update state with feedback
            new_state = dict(state)
            new_state["waiting_for_human"] = False
            new_state["current_feedback_request"] = None
            
            # Store feedback for agent to use in retry
            if "metadata" not in new_state:
                new_state["metadata"] = {}
            if "human_feedback" not in new_state["metadata"]:
                new_state["metadata"]["human_feedback"] = {}
            new_state["metadata"]["human_feedback"][request_id] = {
                "question": current_request.get("question_text"),
                "response": response,
                "agent_name": current_request.get("agent_name")
            }
            
            return new_state
        else:
            # Still waiting for response - but check timeout to prevent infinite loops
            # Track number of wait attempts
            human_feedback_attempts = state.get("human_feedback_attempts", 0)
            MAX_HUMAN_FEEDBACK_ATTEMPTS = 3  # Maximum attempts before skipping
            
            if human_feedback_attempts >= MAX_HUMAN_FEEDBACK_ATTEMPTS:
                logger.warning(
                    f"[HumanFeedback] Timeout waiting for response to request {request_id} "
                    f"after {human_feedback_attempts} attempts. Skipping human feedback and continuing."
                )
                # Skip human feedback and continue
                new_state = dict(state)
                new_state["waiting_for_human"] = False
                new_state["current_feedback_request"] = None
                new_state["human_feedback_attempts"] = 0
                return new_state
            else:
                # Increment attempt counter
                new_state = dict(state)
                new_state["human_feedback_attempts"] = human_feedback_attempts + 1
                logger.info(
                    f"[HumanFeedback] Still waiting for response to request {request_id} "
                    f"(attempt {new_state['human_feedback_attempts']}/{MAX_HUMAN_FEEDBACK_ATTEMPTS})"
                )
                return new_state
    
    def parallel_independent_agents_node(state: AnalysisState) -> AnalysisState:
        """
        Execute independent agents in parallel.
        Independent agents: timeline, key_facts, discrepancy, entity_extraction
        """
        case_id = state.get("case_id", "unknown")
        analysis_types = state.get("analysis_types", [])
        
        # Define independent agents that can run in parallel
        independent_agents = {
            "timeline": timeline_node,
            "key_facts": key_facts_node,
            "discrepancy": discrepancy_node,
            "entity_extraction": entity_extraction_node,
        }
        
        # Filter to only agents that are requested and not yet completed
        agents_to_run = []
        for agent_name, agent_func in independent_agents.items():
            if agent_name in analysis_types:
                # Check if already completed
                result_key = f"{agent_name}_result"
                if state.get(result_key) is None:
                    agents_to_run.append((agent_name, agent_func))
        
        if not agents_to_run:
            logger.info(f"[Parallel] No independent agents to run in parallel for case {case_id}")
            return state
        
        logger.info(f"[Parallel] Running {len(agents_to_run)} independent agents in parallel for case {case_id}")
        
        # Execute agents in parallel using ThreadPoolExecutor
        new_state = dict(state)
        errors = list(state.get("errors", []))
        
        with ThreadPoolExecutor(max_workers=len(agents_to_run)) as executor:
            # Submit all tasks
            future_to_agent = {
                executor.submit(agent_func, state): agent_name
                for agent_name, agent_func in agents_to_run
            }
            
            # Collect results
            for future in as_completed(future_to_agent):
                agent_name = future_to_agent[future]
                try:
                    result_state = future.result()
                    # Merge results into new_state
                    result_key = f"{agent_name}_result"
                    if result_key in result_state:
                        new_state[result_key] = result_state[result_key]
                    # Merge errors
                    if "errors" in result_state:
                        errors.extend(result_state["errors"])
                    logger.info(f"[Parallel] Completed {agent_name} agent")
                except Exception as e:
                    logger.error(f"[Parallel] Error in {agent_name} agent: {e}", exc_info=True)
                    errors.append({
                        "agent": agent_name,
                        "error": str(e)
                    })
        
        new_state["errors"] = errors
        return new_state
    
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
    graph.add_node("evaluation", evaluation_wrapper)
    graph.add_node("adaptation", adaptation_wrapper)
    graph.add_node("parallel_independent", parallel_independent_agents_node)
    graph.add_node("human_feedback_wait", human_feedback_wait_node)
    
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
            "parallel_independent": "parallel_independent",
            "human_feedback_wait": "human_feedback_wait",
            "end": END,
            "supervisor": "supervisor"  # Wait if dependencies not ready
        }
    )
    
    # All agent nodes go to evaluation first, then supervisor
    graph.add_edge("timeline", "evaluation")
    graph.add_edge("key_facts", "evaluation")
    graph.add_edge("discrepancy", "evaluation")
    graph.add_edge("risk", "evaluation")
    graph.add_edge("summary", "evaluation")
    graph.add_edge("document_classifier", "evaluation")
    graph.add_edge("entity_extraction", "evaluation")
    graph.add_edge("privilege_check", "evaluation")
    graph.add_edge("relationship", "evaluation")
    
    # Parallel independent agents node also goes to evaluation
    graph.add_edge("parallel_independent", "evaluation")
    
    # Evaluation node conditionally routes to adaptation, human_feedback, or supervisor
    def route_after_evaluation(state: AnalysisState) -> str:
        """Route after evaluation: adaptation, human_feedback, or supervisor"""
        needs_adaptation = state.get("needs_replanning", False)
        evaluation_result = state.get("evaluation_result", {})
        waiting_for_human = state.get("waiting_for_human", False)
        
        # Check if human feedback is needed first
        if waiting_for_human:
            logger.info(f"[Graph] Routing to human_feedback_wait after evaluation for case {state.get('case_id', 'unknown')}")
            return "human_feedback"
        
        # Check if adaptation is needed
        if needs_adaptation or evaluation_result.get("needs_adaptation", False):
            logger.info(f"[Graph] Routing to adaptation after evaluation for case {state.get('case_id', 'unknown')}")
            return "adaptation"
        else:
            return "supervisor"
    
    graph.add_conditional_edges(
        "evaluation",
        route_after_evaluation,
        {
            "adaptation": "adaptation",
            "human_feedback": "human_feedback_wait",
            "supervisor": "supervisor"
        }
    )
    
    # Human feedback wait node routes back to supervisor (which will check if feedback received)
    graph.add_edge("human_feedback_wait", "supervisor")
    
    # Adaptation node returns to supervisor for replanning
    graph.add_edge("adaptation", "supervisor")
    
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
