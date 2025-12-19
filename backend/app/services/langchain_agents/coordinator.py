"""Agent coordinator for managing multi-agent analysis"""
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from langchain_core.messages import HumanMessage
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
    
    def run_analysis(
        self,
        case_id: str,
        analysis_types: List[str],
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Run analysis using multi-agent system
        
        Args:
            case_id: Case identifier
            analysis_types: List of analysis types to run
            config: Optional configuration for graph execution
        
        Returns:
            Dictionary with analysis results
        """
        start_time = time.time()
        
        try:
            logger.info(f"Starting multi-agent analysis for case {case_id}, types: {analysis_types}")
            
            # Initialize state
            initial_state: AnalysisState = {
                "case_id": case_id,
                "messages": [],
                "timeline_result": None,
                "key_facts_result": None,
                "discrepancy_result": None,
                "risk_result": None,
                "summary_result": None,
                "analysis_types": analysis_types,
                "errors": [],
                "metadata": {}
            }
            
            # Create thread config for graph execution with increased recursion limit
            thread_config = config or {"configurable": {"thread_id": f"case_{case_id}"}}
            # Increase recursion limit to prevent premature termination
            if "configurable" in thread_config:
                thread_config["configurable"]["recursion_limit"] = 50
            else:
                thread_config["recursion_limit"] = 50
            
            # Run graph
            final_state = None
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
                "errors": final_state.get("errors", []) if final_state else [],
                "execution_time": execution_time,
                "metadata": final_state.get("metadata", {}) if final_state else {}
            }
            
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
                "errors": [{"coordinator": str(e)}],
                "execution_time": execution_time,
                "metadata": {}
            }
