"""State definition for LangGraph multi-agent analysis system"""
from typing import TypedDict, List, Dict, Any, Optional
from langchain_core.messages import BaseMessage
from dataclasses import dataclass, field
from enum import Enum
from app.services.langchain_agents.context_schema import CaseContext


class PlanStepStatus(str, Enum):
    """Status of a plan step"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PlanGoal:
    """High-level goal in the analysis plan"""
    goal_id: str
    description: str
    priority: int = 1  # 1 = highest priority
    related_steps: List[str] = field(default_factory=list)  # step_ids that contribute to this goal
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "priority": self.priority,
            "related_steps": self.related_steps,
        }


@dataclass
class PlanStep:
    """A step in the analysis plan with execution parameters"""
    step_id: str
    agent_name: str
    description: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    result_key: Optional[str] = None
    reasoning: Optional[str] = None  # Общее reasoning (для обратной совместимости)
    error: Optional[str] = None
    # New fields for multi-level planning
    parameters: Dict[str, Any] = field(default_factory=dict)  # Execution parameters (depth, focus, etc.)
    estimated_time: Optional[str] = None  # Estimated execution time (e.g., "5-10 мин")
    goal_id: Optional[str] = None  # Which goal this step contributes to
    tools: List[str] = field(default_factory=list)  # Tools to use for this step
    sources: List[str] = field(default_factory=list)  # Data sources to use
    # New fields for detailed reasoning
    planned_reasoning: Optional[str] = None  # Детальное планируемое объяснение
    planned_actions: List[str] = field(default_factory=list)  # Список запланированных действий
    execution_record: Optional[Dict[str, Any]] = None  # Запись о выполнении шага
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_name": self.agent_name,
            "description": self.description,
            "status": self.status.value,
            "dependencies": self.dependencies,
            "result_key": self.result_key,
            "reasoning": self.reasoning or self.planned_reasoning,  # Fallback для обратной совместимости
            "planned_reasoning": self.planned_reasoning,
            "planned_actions": self.planned_actions,
            "execution_record": self.execution_record,
            "error": self.error,
            "parameters": self.parameters,
            "estimated_time": self.estimated_time,
            "goal_id": self.goal_id,
            "tools": self.tools,
            "sources": self.sources,
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
    
    # Case identifier (deprecated: использовать context.case_id)
    case_id: str
    
    # Context (неизменяемые метаданные дела)
    context: Optional[CaseContext]
    
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
    
    # Store references for large results (optimization)
    timeline_ref: Optional[Dict[str, Any]]  # Reference to timeline_result in Store
    key_facts_ref: Optional[Dict[str, Any]]  # Reference to key_facts_result in Store
    discrepancy_ref: Optional[Dict[str, Any]]  # Reference to discrepancy_result in Store
    risk_ref: Optional[Dict[str, Any]]  # Reference to risk_result in Store
    summary_ref: Optional[Dict[str, Any]]  # Reference to summary_result in Store
    classification_ref: Optional[Dict[str, Any]]  # Reference to classification_result in Store
    entities_ref: Optional[Dict[str, Any]]  # Reference to entities_result in Store
    privilege_ref: Optional[Dict[str, Any]]  # Reference to privilege_result in Store
    relationship_ref: Optional[Dict[str, Any]]  # Reference to relationship_result in Store
    
    # Analysis types requested
    analysis_types: List[str]
    
    # Errors encountered during execution
    errors: List[Dict[str, Any]]
    
    # Metadata for tracking
    metadata: Dict[str, Any]
    
    # === NEW: Adaptive Agent Fields ===
    
    # High-level goals for the analysis
    plan_goals: List[Dict[str, Any]]  # List of PlanGoal.to_dict()
    
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

    # === NEW: LEGORA Workflow Fields ===
    
    # Result of UNDERSTAND phase
    understanding_result: Optional[Dict[str, Any]]  # Result from understand_node
    
    # Result of DELIVER phase
    delivery_result: Optional[Dict[str, Any]]  # Result from deliver_node (tables, reports, formatted output)
    
    # Table results from DELIVER phase
    table_results: Optional[Dict[str, Any]]  # Dictionary of analysis_type -> table_id or table_path
    
    # Result of Deep Analysis phase
    deep_analysis_result: Optional[Dict[str, Any]]  # Result from deep_analysis_node

    # === NEW: File System Context Fields ===
    
    # Workspace path for file system context
    workspace_path: Optional[str]  # Path to workspace directory
    
    # List of files in workspace (updated dynamically)
    workspace_files: List[str]  # List of file paths relative to workspace
    
    # Current working file (if agent is editing a file)
    current_working_file: Optional[str]  # Current file being edited


def create_initial_state(
    case_id: str,
    analysis_types: List[str],
    metadata: Optional[Dict[str, Any]] = None,
    context: Optional[CaseContext] = None
) -> AnalysisState:
    """
    Create initial state for analysis
    
    Args:
        case_id: Case identifier
        analysis_types: List of analysis types to run
        metadata: Optional metadata
        context: Optional CaseContext (если не передан, создаётся минимальный из case_id)
        
    Returns:
        Initialized AnalysisState
    """
    # Создаём минимальный context если не передан
    if context is None:
        from app.services.langchain_agents.context_schema import CaseContext
        context = CaseContext.from_minimal(case_id=case_id)
    
    return AnalysisState(
        case_id=case_id,
        context=context,
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
        # Store references
        timeline_ref=None,
        key_facts_ref=None,
        discrepancy_ref=None,
        risk_ref=None,
        summary_ref=None,
        classification_ref=None,
        entities_ref=None,
        privilege_ref=None,
        relationship_ref=None,
        analysis_types=analysis_types,
        errors=[],
        metadata=metadata or {},
        # Adaptive fields
        plan_goals=[],
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
        # File System Context fields
        workspace_path=None,
        workspace_files=[],
        current_working_file=None,
    )
