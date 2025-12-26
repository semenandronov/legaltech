"""Agent Interaction models for human-in-the-loop functionality"""
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.models.case import Base


class AgentInteraction(Base):
    """
    AgentInteraction model - stores human-in-the-loop interactions.
    
    This enables Harvey-like agent behavior where agents can:
    1. Ask clarifying questions to users
    2. Request confirmation for important decisions
    3. Present multiple choice options
    """
    __tablename__ = "agent_interactions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Agent information
    agent_name = Column(String(100), nullable=False)  # e.g., "risk", "timeline"
    step_id = Column(String(255), nullable=True)  # Reference to plan step
    
    # Question details
    question_type = Column(String(50), nullable=False)  # clarification, confirmation, choice
    question_text = Column(Text, nullable=False)
    context = Column(Text, nullable=True)  # Additional context for the question
    
    # Options for choice questions
    options = Column(JSON, nullable=True)  # [{"id": "a", "label": "Option A", "description": "..."}, ...]
    
    # User response
    user_response = Column(Text, nullable=True)
    selected_option_id = Column(String(50), nullable=True)  # For choice questions
    
    # Status tracking
    status = Column(String(50), default="pending")  # pending, answered, timeout, cancelled
    is_blocking = Column(Boolean, default=True)  # Whether agent waits for response
    
    # Timing
    created_at = Column(DateTime, default=datetime.utcnow)
    answered_at = Column(DateTime, nullable=True)
    timeout_at = Column(DateTime, nullable=True)  # When to timeout if not answered
    
    # Relationships
    case = relationship("Case", backref="agent_interactions")
    user = relationship("User", backref="agent_interactions")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "case_id": self.case_id,
            "agent_name": self.agent_name,
            "step_id": self.step_id,
            "question_type": self.question_type,
            "question_text": self.question_text,
            "context": self.context,
            "options": self.options,
            "user_response": self.user_response,
            "selected_option_id": self.selected_option_id,
            "status": self.status,
            "is_blocking": self.is_blocking,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
        }
    
    @classmethod
    def create_clarification(
        cls,
        case_id: str,
        user_id: str,
        agent_name: str,
        question_text: str,
        context: str = None,
        step_id: str = None
    ):
        """Create a clarification question"""
        return cls(
            case_id=case_id,
            user_id=user_id,
            agent_name=agent_name,
            step_id=step_id,
            question_type="clarification",
            question_text=question_text,
            context=context,
            is_blocking=True,
        )
    
    @classmethod
    def create_confirmation(
        cls,
        case_id: str,
        user_id: str,
        agent_name: str,
        question_text: str,
        context: str = None,
        step_id: str = None
    ):
        """Create a confirmation (yes/no) question"""
        return cls(
            case_id=case_id,
            user_id=user_id,
            agent_name=agent_name,
            step_id=step_id,
            question_type="confirmation",
            question_text=question_text,
            context=context,
            options=[
                {"id": "yes", "label": "Да"},
                {"id": "no", "label": "Нет"},
            ],
            is_blocking=True,
        )
    
    @classmethod
    def create_choice(
        cls,
        case_id: str,
        user_id: str,
        agent_name: str,
        question_text: str,
        options: list,
        context: str = None,
        step_id: str = None
    ):
        """Create a multiple choice question"""
        return cls(
            case_id=case_id,
            user_id=user_id,
            agent_name=agent_name,
            step_id=step_id,
            question_type="choice",
            question_text=question_text,
            context=context,
            options=options,
            is_blocking=True,
        )


class AgentExecutionLog(Base):
    """
    AgentExecutionLog model - stores detailed execution logs for transparency.
    
    Provides visibility into what agents are doing (like Harvey's transparency).
    """
    __tablename__ = "agent_execution_logs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id = Column(String, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Execution context
    execution_id = Column(String(255), nullable=False, index=True)  # Groups logs for one run
    agent_name = Column(String(100), nullable=False)
    step_id = Column(String(255), nullable=True)
    
    # Log details
    log_type = Column(String(50), nullable=False)  # start, progress, result, error, decision
    message = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)  # Additional structured data
    
    # Timing
    timestamp = Column(DateTime, default=datetime.utcnow)
    duration_ms = Column(String, nullable=True)  # Duration if applicable
    
    # Relationships
    case = relationship("Case", backref="agent_logs")
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "agent_name": self.agent_name,
            "step_id": self.step_id,
            "log_type": self.log_type,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "duration_ms": self.duration_ms,
        }
    
    @classmethod
    def log_start(cls, case_id: str, execution_id: str, agent_name: str, step_id: str = None):
        """Log agent start"""
        return cls(
            case_id=case_id,
            execution_id=execution_id,
            agent_name=agent_name,
            step_id=step_id,
            log_type="start",
            message=f"Агент {agent_name} начал выполнение",
        )
    
    @classmethod
    def log_progress(
        cls, 
        case_id: str, 
        execution_id: str, 
        agent_name: str, 
        message: str,
        details: dict = None,
        step_id: str = None
    ):
        """Log progress update"""
        return cls(
            case_id=case_id,
            execution_id=execution_id,
            agent_name=agent_name,
            step_id=step_id,
            log_type="progress",
            message=message,
            details=details,
        )
    
    @classmethod
    def log_decision(
        cls,
        case_id: str,
        execution_id: str,
        agent_name: str,
        decision: str,
        reasoning: str,
        step_id: str = None
    ):
        """Log a decision made by the agent"""
        return cls(
            case_id=case_id,
            execution_id=execution_id,
            agent_name=agent_name,
            step_id=step_id,
            log_type="decision",
            message=decision,
            details={"reasoning": reasoning},
        )
    
    @classmethod
    def log_result(
        cls,
        case_id: str,
        execution_id: str,
        agent_name: str,
        success: bool,
        summary: str,
        duration_ms: int = None,
        step_id: str = None
    ):
        """Log agent result"""
        return cls(
            case_id=case_id,
            execution_id=execution_id,
            agent_name=agent_name,
            step_id=step_id,
            log_type="result",
            message=f"{'✓' if success else '✗'} {summary}",
            details={"success": success},
            duration_ms=str(duration_ms) if duration_ms else None,
        )
    
    @classmethod
    def log_error(
        cls,
        case_id: str,
        execution_id: str,
        agent_name: str,
        error: str,
        step_id: str = None
    ):
        """Log an error"""
        return cls(
            case_id=case_id,
            execution_id=execution_id,
            agent_name=agent_name,
            step_id=step_id,
            log_type="error",
            message=f"Ошибка: {error}",
            details={"error": error},
        )

