"""Agent coordinator for managing multi-agent analysis"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState, create_initial_state
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.human_feedback import get_feedback_service
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import time

logger = logging.getLogger(__name__)


class AgentCoordinator:
    """Coordinator for managing multi-agent analysis workflow"""
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Initialize agent coordinator
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        
        # Create graph
        self.graph = create_analysis_graph(db, rag_service, document_processor)
        
        # Initialize planning agent
        try:
            self.planning_agent = PlanningAgent()
        except Exception as e:
            logger.warning(f"Failed to initialize PlanningAgent: {e}, will use analysis_types directly")
            self.planning_agent = None
        
        # Initialize human feedback service
        self.feedback_service = get_feedback_service(db)
    
    def run_analysis(
        self,
        case_id: str,
        analysis_types: List[str],
        user_task: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        websocket_callback: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Run analysis using multi-agent system
        
        Args:
            case_id: Case identifier
            analysis_types: List of analysis types to run (if user_task not provided)
            user_task: Optional natural language task description (will use PlanningAgent)
            config: Optional configuration for graph execution
            websocket_callback: Optional async callback for sending messages via WebSocket
        
        Returns:
            Dictionary with analysis results
        """
        start_time = time.time()
        
        try:
            logger.info(f"Starting multi-agent analysis for case {case_id}, types: {analysis_types}")
            
            # Use PlanningAgent if user_task provided
            if user_task and self.planning_agent:
                try:
                    # Get case info to pass document information
                    from app.models.case import Case
                    case = self.db.query(Case).filter(Case.id == case_id).first()
                    num_documents = case.num_documents if case else 0
                    file_names = case.file_names if case and case.file_names else []
                    
                    plan = self.planning_agent.plan_analysis(
                        user_task, 
                        case_id,
                        available_documents=file_names[:10] if file_names else None,
                        num_documents=num_documents
                    )
                    analysis_types = plan.get("analysis_types", analysis_types)
                    logger.info(f"PlanningAgent created plan: {analysis_types}, reasoning: {plan.get('reasoning', '')[:100]}")
                    
                    # Create initial plan steps
                    from app.services.langchain_agents.state import PlanStep, PlanStepStatus
                    current_plan = []
                    for idx, agent_name in enumerate(analysis_types):
                        step = PlanStep(
                            step_id=f"{agent_name}_{case_id}_{idx}",
                            agent_name=agent_name,
                            description=f"Execute {agent_name} analysis",
                            status=PlanStepStatus.PENDING,
                            result_key=f"{agent_name}_result"
                        )
                        current_plan.append(step.to_dict())
                except Exception as e:
                    logger.warning(f"PlanningAgent failed: {e}, using provided analysis_types")
                    current_plan = []
            else:
                current_plan = []
            
            # Register WebSocket callback for human feedback if provided
            if websocket_callback:
                self.feedback_service.register_websocket_callback(case_id, websocket_callback)
            
            # Initialize state using create_initial_state helper
            initial_state = create_initial_state(
                case_id=case_id,
                analysis_types=analysis_types,
                metadata={"planning_used": user_task is not None and self.planning_agent is not None}
            )
            
            # Add current_plan if created
            if current_plan:
                initial_state["current_plan"] = current_plan
            
            # Create thread config for graph execution with increased recursion limit
            thread_config = config or {"configurable": {"thread_id": f"case_{case_id}"}}
            # Increase recursion limit to prevent premature termination
            if "configurable" in thread_config:
                thread_config["configurable"]["recursion_limit"] = 50
            else:
                thread_config["recursion_limit"] = 50
            
            # Run graph with parallel processing for independent agents
            # Note: LangGraph handles parallelization internally, but we can optimize
            # by running independent analysis types in parallel batches
            final_state = None
            
            # Check if we can run independent agents in parallel
            independent_types = ["timeline", "key_facts", "discrepancy", "entity_extraction", "document_classifier"]
            dependent_types = ["risk", "summary", "privilege_check", "relationship"]  # relationship depends on entities
            
            # If only independent types, we can optimize
            if all(at in independent_types for at in analysis_types) and len(analysis_types) > 1:
                logger.info(f"Running {len(analysis_types)} independent agents, using optimized execution")
                # LangGraph will handle this, but we log it for monitoring
            
            for state in self.graph.stream(initial_state, thread_config):
                # Log progress
                node_name = list(state.keys())[0] if state else "unknown"
                logger.info(f"Graph execution: {node_name} completed")
                final_state = state[node_name] if state else None
            
            # Get final state
            if final_state is None:
                # Try to get final state from graph
                final_state = self.graph.get_state(thread_config).values
            
            execution_time = time.time() - start_time
            
            # Track agent execution metrics
            from app.middleware.metrics import track_agent_execution
            track_agent_execution("multi_agent_analysis", execution_time, success=True)
            
            logger.info(
                f"Multi-agent analysis completed for case {case_id} in {execution_time:.2f}s"
            )
            
            # Extract results
            results = {
                "case_id": case_id,
                "timeline": final_state.get("timeline_result") if final_state else None,
                "key_facts": final_state.get("key_facts_result") if final_state else None,
                "discrepancies": final_state.get("discrepancy_result") if final_state else None,
                "risk_analysis": final_state.get("risk_result") if final_state else None,
                "summary": final_state.get("summary_result") if final_state else None,
                "classification": final_state.get("classification_result") if final_state else None,
                "entities": final_state.get("entities_result") if final_state else None,
                "privilege": final_state.get("privilege_result") if final_state else None,
                "errors": final_state.get("errors", []) if final_state else [],
                "execution_time": execution_time,
                "metadata": final_state.get("metadata", {}) if final_state else {},
                "adaptation_history": final_state.get("adaptation_history", []) if final_state else [],
                "evaluation_results": final_state.get("evaluation_result") if final_state else None
            }
            
            # Unregister WebSocket callback
            if websocket_callback:
                self.feedback_service.unregister_websocket_callback(case_id)
            
            return results
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(
                f"Error in multi-agent analysis for case {case_id}: {e}",
                exc_info=True
            )
            
            return {
                "case_id": case_id,
                "timeline": None,
                "key_facts": None,
                "discrepancies": None,
                "risk_analysis": None,
                "summary": None,
                "classification": None,
                "entities": None,
                "privilege": None,
                "errors": [{"coordinator": str(e)}],
                "execution_time": execution_time,
                "metadata": {}
            }
