"""Workflow Executor - executes workflows through LangGraph"""
from typing import Dict, Any, Optional, AsyncIterator, List
from sqlalchemy.orm import Session
from app.models.workflow_template import WorkflowTemplate
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState, create_initial_state
from app.services.langchain_agents.workflow_graph_builder import WorkflowGraphBuilder
import logging
import json

logger = logging.getLogger(__name__)


class WorkflowExecutionEvent:
    """Event emitted during workflow execution"""
    def __init__(
        self,
        event_type: str,
        data: Dict[str, Any],
        step_id: Optional[str] = None
    ):
        self.event_type = event_type  # "step_started", "step_completed", "error", "completed"
        self.data = data
        self.step_id = step_id
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "step_id": self.step_id
        }


class WorkflowExecutor:
    """
    Исполняет workflows через LangGraph.
    
    Преобразует статические workflow templates в динамические исполняемые графы.
    """
    
    def __init__(
        self,
        db: Session,
        rag_service: RAGService = None,
        document_processor: DocumentProcessor = None
    ):
        """
        Initialize WorkflowExecutor
        
        Args:
            db: Database session
            rag_service: RAG service instance
            document_processor: Document processor instance
        """
        self.db = db
        self.rag_service = rag_service
        self.document_processor = document_processor
        self.graph_builder = WorkflowGraphBuilder(
            rag_service=rag_service,
            document_processor=document_processor
        )
    
    async def execute_workflow(
        self,
        workflow_id: str,
        case_id: str,
        user_input: str,
        user_id: str
    ) -> AsyncIterator[WorkflowExecutionEvent]:
        """
        Streaming execution of workflow
        
        Args:
            workflow_id: Workflow template ID
            case_id: Case ID to analyze
            user_input: User input/query for the workflow
            user_id: User ID
            
        Yields:
            WorkflowExecutionEvent objects
        """
        try:
            # Load workflow template
            workflow = self.db.query(WorkflowTemplate).filter(
                WorkflowTemplate.id == workflow_id
            ).first()
            
            if not workflow:
                yield WorkflowExecutionEvent(
                    event_type="error",
                    data={"error": f"Workflow {workflow_id} not found"}
                )
                return
            
            logger.info(f"Executing workflow {workflow_id} for case {case_id}")
            
            # Build graph from template
            graph = self.graph_builder.build_graph(workflow, self.db)
            
            # Determine analysis types from workflow steps
            analysis_types = self._extract_analysis_types(workflow)
            
            # Create initial state
            initial_state = create_initial_state(
                case_id=case_id,
                analysis_types=analysis_types,
                metadata={
                    "user_task": user_input,
                    "user_id": user_id,
                    "workflow_id": workflow_id,
                    "workflow_name": workflow.display_name
                }
            )
            
            # Execute graph with streaming
            config = {"configurable": {"thread_id": f"workflow_{workflow_id}_{case_id}"}}
            
            # Stream execution
            try:
                async for event in graph.astream(initial_state, config=config):
                    # Yield events for each step
                    for node_name, node_state in event.items():
                        yield WorkflowExecutionEvent(
                            event_type="step_completed",
                            data={
                                "node": node_name,
                                "state_snapshot": self._create_state_snapshot(node_state)
                            },
                            step_id=node_name
                        )
                
                # Final state (get from last event)
                final_state = initial_state  # Will be updated in loop
            except AttributeError:
                # Fallback if astream not available - use invoke
                logger.warning("astream not available, using invoke instead")
                final_state = await graph.ainvoke(initial_state, config=config)
            yield WorkflowExecutionEvent(
                event_type="completed",
                data={
                    "results": self._extract_workflow_results(final_state),
                    "workflow_id": workflow_id
                }
            )
            
        except Exception as e:
            logger.error(f"Error executing workflow {workflow_id}: {e}", exc_info=True)
            yield WorkflowExecutionEvent(
                event_type="error",
                data={"error": str(e), "workflow_id": workflow_id}
            )
    
    def _extract_analysis_types(self, workflow: WorkflowTemplate) -> List[str]:
        """Extract analysis types from workflow steps"""
        analysis_types = []
        agent_mapping = {
            "classification": "document_classifier",
            "entity_extraction": "entity_extraction",
            "timeline": "timeline",
            "key_facts": "key_facts",
            "discrepancy": "discrepancy",
            "risk": "risk",
            "summary": "summary",
            "privilege_check": "privilege_check",
            "relationship": "relationship"
        }
        
        for step in workflow.steps or []:
            agent_name = step.get("agent", "")
            if agent_name in agent_mapping:
                analysis_type = agent_mapping[agent_name]
                if analysis_type not in analysis_types:
                    analysis_types.append(analysis_type)
        
        return analysis_types if analysis_types else ["key_facts"]  # Default fallback
    
    def _create_state_snapshot(self, state: AnalysisState) -> Dict[str, Any]:
        """Create a snapshot of state for event"""
        return {
            "case_id": state.get("case_id"),
            "completed_steps": state.get("completed_steps", []),
            "errors": state.get("errors", []),
            "current_step_id": state.get("current_step_id")
        }
    
    def _extract_workflow_results(self, state: AnalysisState) -> Dict[str, Any]:
        """Extract results from final state"""
        return {
            "timeline": state.get("timeline_result"),
            "key_facts": state.get("key_facts_result"),
            "discrepancy": state.get("discrepancy_result"),
            "risk": state.get("risk_result"),
            "summary": state.get("summary_result"),
            "classification": state.get("classification_result"),
            "entities": state.get("entities_result"),
            "privilege": state.get("privilege_result"),
            "relationship": state.get("relationship_result")
        }

