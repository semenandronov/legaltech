"""Metrics for tracking planning and execution quality"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Float, Integer, JSON, Text
from app.models.case import Base
import logging

logger = logging.getLogger(__name__)


class PlanningMetrics(Base):
    """Stores metrics for planning and execution quality"""
    __tablename__ = "planning_metrics"
    
    id = Column(String, primary_key=True)
    case_id = Column(String, nullable=False, index=True)
    user_id = Column(String, nullable=True, index=True)
    
    # Planning metrics
    planning_time_seconds = Column(Float, nullable=True)
    plan_confidence = Column(Float, nullable=True)
    plan_validation_passed = Column(String, nullable=True)  # "true"/"false"
    plan_issues_count = Column(Integer, default=0)
    
    # Execution metrics
    execution_time_seconds = Column(Float, nullable=True)
    total_steps = Column(Integer, default=0)
    completed_steps = Column(Integer, default=0)
    failed_steps = Column(Integer, default=0)
    adaptations_count = Column(Integer, default=0)
    
    # Quality metrics
    average_confidence = Column(Float, nullable=True)
    average_completeness = Column(Float, nullable=True)
    average_accuracy = Column(Float, nullable=True)
    
    # Plan details
    plan_goals_count = Column(Integer, default=0)
    plan_strategy = Column(String, nullable=True)
    tools_used = Column(JSON, nullable=True)
    sources_used = Column(JSON, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Additional metadata
    metrics_metadata = Column("metadata", JSON, nullable=True)


class MetricsCollector:
    """
    Collects and aggregates metrics for planning and execution quality
    """
    
    def __init__(self, db: Session):
        """Initialize metrics collector"""
        self.db = db
    
    def record_planning_metrics(
        self,
        case_id: str,
        user_id: Optional[str],
        plan: Dict[str, Any],
        planning_time: float,
        validation_result: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Records planning metrics
        
        Args:
            case_id: Case identifier
            user_id: User identifier
            plan: Plan dictionary
            planning_time: Time taken for planning (seconds)
            validation_result: Optional validation result
        
        Returns:
            Metrics record ID
        """
        import uuid
        
        metrics_id = str(uuid.uuid4())
        
        plan_confidence = plan.get("confidence", 0.0)
        plan_goals = plan.get("goals", [])
        plan_strategy = plan.get("strategy", "unknown")
        
        validation_passed = "true"
        issues_count = 0
        if validation_result:
            validation_passed = "true" if validation_result.get("is_valid", False) else "false"
            issues_count = len(validation_result.get("issues", []))
        
        # Extract tools and sources from steps
        tools_used = []
        sources_used = []
        steps = plan.get("steps", [])
        for step in steps:
            step_tools = step.get("tools", [])
            step_sources = step.get("sources", [])
            tools_used.extend(step_tools)
            sources_used.extend(step_sources)
        
        tools_used = list(set(tools_used))  # Remove duplicates
        sources_used = list(set(sources_used))
        
        metrics = PlanningMetrics(
            id=metrics_id,
            case_id=case_id,
            user_id=user_id,
            planning_time_seconds=planning_time,
            plan_confidence=plan_confidence,
            plan_validation_passed=validation_passed,
            plan_issues_count=issues_count,
            plan_goals_count=len(plan_goals),
            plan_strategy=plan_strategy,
            tools_used=tools_used,
            sources_used=sources_used,
            total_steps=len(steps) if steps else len(plan.get("analysis_types", [])),
            metrics_metadata={"plan": plan}
        )
        
        self.db.add(metrics)
        self.db.commit()
        
        logger.info(f"Recorded planning metrics for case {case_id}: {metrics_id}")
        return metrics_id
    
    def update_execution_metrics(
        self,
        metrics_id: str,
        execution_time: float,
        completed_steps: int,
        failed_steps: int,
        adaptations_count: int,
        quality_metrics: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Updates execution metrics
        
        Args:
            metrics_id: Metrics record ID
            execution_time: Total execution time (seconds)
            completed_steps: Number of completed steps
            failed_steps: Number of failed steps
            adaptations_count: Number of adaptations
            quality_metrics: Optional quality metrics
        """
        metrics = self.db.query(PlanningMetrics).filter(
            PlanningMetrics.id == metrics_id
        ).first()
        
        if not metrics:
            logger.warning(f"Metrics record {metrics_id} not found")
            return
        
        metrics.execution_time_seconds = execution_time
        metrics.completed_steps = completed_steps
        metrics.failed_steps = failed_steps
        metrics.adaptations_count = adaptations_count
        metrics.completed_at = datetime.utcnow()
        
        if quality_metrics:
            metrics.average_confidence = quality_metrics.get("average_confidence")
            metrics.average_completeness = quality_metrics.get("average_completeness")
            metrics.average_accuracy = quality_metrics.get("average_accuracy")
        
        self.db.commit()
        
        logger.info(f"Updated execution metrics for {metrics_id}")
    
    def get_metrics_summary(
        self,
        case_id: Optional[str] = None,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Gets aggregated metrics summary
        
        Args:
            case_id: Optional case ID filter
            user_id: Optional user ID filter
            days: Number of days to look back
        
        Returns:
            Dictionary with aggregated metrics
        """
        query = self.db.query(PlanningMetrics)
        
        if case_id:
            query = query.filter(PlanningMetrics.case_id == case_id)
        if user_id:
            query = query.filter(PlanningMetrics.user_id == user_id)
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        query = query.filter(PlanningMetrics.created_at >= cutoff_date)
        
        metrics_list = query.all()
        
        if not metrics_list:
            return {
                "total_plans": 0,
                "average_planning_time": 0.0,
                "average_execution_time": 0.0,
                "success_rate": 0.0,
                "average_confidence": 0.0
            }
        
        total_plans = len(metrics_list)
        total_planning_time = sum(m.planning_time_seconds or 0 for m in metrics_list)
        total_execution_time = sum(m.execution_time_seconds or 0 for m in metrics_list)
        total_completed = sum(m.completed_steps or 0 for m in metrics_list)
        total_failed = sum(m.failed_steps or 0 for m in metrics_list)
        total_steps = sum(m.total_steps or 0 for m in metrics_list)
        total_confidence = sum(m.plan_confidence or 0 for m in metrics_list)
        
        success_rate = (
            total_completed / total_steps if total_steps > 0 else 0.0
        )
        
        return {
            "total_plans": total_plans,
            "average_planning_time": total_planning_time / total_plans if total_plans > 0 else 0.0,
            "average_execution_time": total_execution_time / total_plans if total_plans > 0 else 0.0,
            "success_rate": success_rate,
            "average_confidence": total_confidence / total_plans if total_plans > 0 else 0.0,
            "average_adaptations": sum(m.adaptations_count or 0 for m in metrics_list) / total_plans if total_plans > 0 else 0.0,
            "failure_rate": total_failed / total_steps if total_steps > 0 else 0.0
        }

