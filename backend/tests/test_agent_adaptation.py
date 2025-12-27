"""Tests for agent adaptation functionality"""
import pytest
from app.services.langchain_agents.adaptation_engine import AdaptationEngine
from app.services.langchain_agents.state import AnalysisState, PlanStep, PlanStepStatus


def test_adaptation_engine_should_adapt():
    """Test that adaptation engine correctly identifies when adaptation is needed"""
    engine = AdaptationEngine()
    
    # Create state with errors
    state: AnalysisState = {
        "case_id": "test_case",
        "messages": [],
        "timeline_result": None,
        "key_facts_result": None,
        "discrepancy_result": None,
        "risk_result": None,
        "summary_result": None,
        "classification_result": None,
        "entities_result": None,
        "privilege_result": None,
        "relationship_result": None,
        "analysis_types": ["timeline", "key_facts"],
        "errors": [{"agent": "timeline", "error": "Test error"}],
        "metadata": {},
        "current_plan": [],
        "completed_steps": [],
        "adaptation_history": [],
        "needs_replanning": False,
        "evaluation_result": None,
        "current_step_id": None,
        "pending_feedback": [],
        "feedback_responses": {},
        "waiting_for_human": False,
        "current_feedback_request": None,
    }
    
    evaluation = {
        "needs_adaptation": True,
        "confidence": 0.3,
        "completeness": 0.4,
        "issues": ["Low confidence", "Incomplete results"]
    }
    
    should_adapt = engine.should_adapt(state, evaluation)
    assert should_adapt is True


def test_adaptation_engine_retry_strategy():
    """Test retry strategy for failed steps"""
    engine = AdaptationEngine()
    
    state: AnalysisState = {
        "case_id": "test_case",
        "messages": [],
        "timeline_result": None,
        "key_facts_result": None,
        "discrepancy_result": None,
        "risk_result": None,
        "summary_result": None,
        "classification_result": None,
        "entities_result": None,
        "privilege_result": None,
        "relationship_result": None,
        "analysis_types": ["timeline"],
        "errors": [],
        "metadata": {},
        "current_plan": [
            {
                "step_id": "timeline_1",
                "agent_name": "timeline",
                "description": "Extract timeline",
                "status": PlanStepStatus.FAILED.value,
                "dependencies": [],
                "result_key": "timeline_result",
                "error": "Test error"
            }
        ],
        "completed_steps": [],
        "adaptation_history": [],
        "needs_replanning": True,
        "evaluation_result": {"needs_retry": True},
        "current_step_id": None,
        "pending_feedback": [],
        "feedback_responses": {},
        "waiting_for_human": False,
        "current_feedback_request": None,
    }
    
    evaluation = {"needs_retry": True}
    
    adapted_state = engine.adapt_plan(state, evaluation, trigger="evaluation")
    
    # Check that failed step is now pending
    adapted_plan = adapted_state.get("current_plan", [])
    assert len(adapted_plan) > 0
    assert adapted_plan[0]["status"] == PlanStepStatus.PENDING.value
    assert adapted_plan[0]["error"] is None


def test_adaptation_engine_skip_strategy():
    """Test skip strategy after multiple failures"""
    engine = AdaptationEngine()
    
    state: AnalysisState = {
        "case_id": "test_case",
        "messages": [],
        "timeline_result": None,
        "key_facts_result": None,
        "discrepancy_result": None,
        "risk_result": None,
        "summary_result": None,
        "classification_result": None,
        "entities_result": None,
        "privilege_result": None,
        "relationship_result": None,
        "analysis_types": ["timeline"],
        "errors": [],
        "metadata": {"retry_count": 3},  # Already retried multiple times
        "current_plan": [
            {
                "step_id": "timeline_1",
                "agent_name": "timeline",
                "description": "Extract timeline",
                "status": PlanStepStatus.FAILED.value,
                "dependencies": [],
                "result_key": "timeline_result",
                "error": "Test error"
            }
        ],
        "completed_steps": [],
        "adaptation_history": [],
        "needs_replanning": True,
        "evaluation_result": {"needs_retry": True},
        "current_step_id": None,
        "pending_feedback": [],
        "feedback_responses": {},
        "waiting_for_human": False,
        "current_feedback_request": None,
    }
    
    evaluation = {"needs_retry": True}
    
    adapted_state = engine.adapt_plan(state, evaluation, trigger="evaluation")
    
    # Check that failed step is now skipped
    adapted_plan = adapted_state.get("current_plan", [])
    assert len(adapted_plan) > 0
    assert adapted_plan[0]["status"] == PlanStepStatus.SKIPPED.value

