"""State definition for LangGraph multi-agent analysis system"""
from typing import TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from dataclasses import dataclass, field
from enum import Enum


class PlanStepStatus(str, Enum):
    """Status of a plan step"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanStep:
    """A step in the analysis plan"""
    step_id: str
    agent_name: str
    description: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    result_key: Optional[str] = None
    reasoning: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_name": self.agent_name,
            "description": self.description,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "result_key": self.result_key,
            "reasoning": self.reasoning,
            "error": self.error,
        }


@dataclass 
class AdaptationRecord:
    """Record of a plan adaptation"""
    timestamp: str
    reason: str
    original_plan: List[str]
    new_plan: List[str]
    trigger: str  # "error", "user_feedback", "result_evaluation"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "reason": self.reason,
            "original_plan": self.original_plan,
            "new_plan": self.new_plan,
            "trigger": self.trigger,
        }


@dataclass
class HumanFeedbackRequest:
    """Request for human feedback/clarification"""
    request_id: str
    agent_name: str
    question_type: str  # "clarification", "confirmation", "choice"
    question_text: str
    options: Optional[List[Dict[str, str]]] = None
    context: Optional[str] = None
    response: Optional[str] = None
    status: str = "pending"  # "pending", "answered", "timeout"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "agent_name": self.agent_name,
            "question_type": self.question_type,
            "question_text": self.question_text,
            "options": self.options,
            "context": self.context,
            "response": self.response,
            "status": self.status,
        }


class AnalysisState(TypedDict):
    """State object for the analysis graph"""
    
    # Case identifier
    case_id: str
    
    # Messages for agent communication
    messages: List[BaseMessage]
    
    # Results from each agent
    timeline_result: Optional[Dict[str, Any]]
    key_facts_result: Optional[Dict[str, Any]]
    discrepancy_result: Optional[Dict[str, Any]]
    risk_result: Optional[Dict[str, Any]]
    summary_result: Optional[Dict[str, Any]]
    classification_result: Optional[Dict[str, Any]]  # Document classification
    entities_result: Optional[Dict[str, Any]]  # Entity extraction
    privilege_result: Optional[Dict[str, Any]]  # Privilege check
    relationship_result: Optional[Dict[str, Any]]  # Relationship graph
    
    # Analysis types requested
    analysis_types: List[str]
    
    # Errors encountered during execution
    errors: List[Dict[str, Any]]
    
    # Metadata for tracking
    metadata: Dict[str, Any]
    
    # === NEW: Adaptive Agent Fields ===
    
    # Current execution plan with steps
    current_plan: List[Dict[str, Any]]  # List of PlanStep.to_dict()
    
    # Completed step IDs
    completed_steps: List[str]
    
    # History of plan adaptations
    adaptation_history: List[Dict[str, Any]]  # List of AdaptationRecord.to_dict()
    
    # Flag indicating need for replanning
    needs_replanning: bool
    
    # Result of last evaluation
    evaluation_result: Optional[Dict[str, Any]]
    
    # Current step being executed
    current_step_id: Optional[str]
    
    # === NEW: Human-in-the-loop Fields ===
    
    # Pending human feedback requests
    pending_feedback: List[Dict[str, Any]]  # List of HumanFeedbackRequest.to_dict()
    
    # Collected feedback responses
    feedback_responses: Dict[str, str]  # request_id -> response
    
    # Flag indicating agent is waiting for human input
    waiting_for_human: bool
    
    # Current feedback request (if waiting)
    current_feedback_request: Optional[Dict[str, Any]]


def create_initial_state(
    case_id: str,
    analysis_types: List[str],
    metadata: Optional[Dict[str, Any]] = None
) -> AnalysisState:
    """
    Create initial state for analysis
    
    Args:
        case_id: Case identifier
        analysis_types: List of analysis types to run
        metadata: Optional metadata
        
    Returns:
        Initialized AnalysisState
    """
    return AnalysisState(
        case_id=case_id,
        messages=[],
        timeline_result=None,
        key_facts_result=None,
        discrepancy_result=None,
        risk_result=None,
        summary_result=None,
        classification_result=None,
        entities_result=None,
        privilege_result=None,
        relationship_result=None,
        analysis_types=analysis_types,
        errors=[],
        metadata=metadata or {},
        # Adaptive fields
        current_plan=[],
        completed_steps=[],
        adaptation_history=[],
        needs_replanning=False,
        evaluation_result=None,
        current_step_id=None,
        # Human-in-the-loop fields
        pending_feedback=[],
        feedback_responses={},
        waiting_for_human=False,
        current_feedback_request=None,
    )
