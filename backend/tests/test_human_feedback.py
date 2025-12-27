"""Tests for human feedback functionality"""
import pytest
from app.services.langchain_agents.evaluation_node import evaluation_node
from app.services.langchain_agents.state import AnalysisState


def test_evaluation_creates_human_feedback_request():
    """Test that evaluation creates human feedback request when confidence is low"""
    state: AnalysisState = {
        "case_id": "test_case",
        "messages": [],
        "timeline_result": {
            "events": [],
            "total_events": 0
        },
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
                "status": "pending",
                "dependencies": [],
                "result_key": "timeline_result"
            }
        ],
        "completed_steps": [],
        "adaptation_history": [],
        "needs_replanning": False,
        "evaluation_result": None,
        "current_step_id": "timeline_1",
        "pending_feedback": [],
        "feedback_responses": {},
        "waiting_for_human": False,
        "current_feedback_request": None,
    }
    
    # Run evaluation
    result_state = evaluation_node(state, db=None, rag_service=None, document_processor=None)
    
    # Check that human feedback request was created
    assert result_state.get("waiting_for_human") is True
    assert result_state.get("current_feedback_request") is not None
    assert len(result_state.get("pending_feedback", [])) > 0
    
    # Check feedback request content
    feedback_request = result_state.get("current_feedback_request")
    assert feedback_request.get("agent_name") == "timeline"
    assert feedback_request.get("question_type") == "clarification"


def test_human_feedback_wait_node():
    """Test human feedback wait node behavior"""
    from app.services.langchain_agents.graph import create_analysis_graph
    
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
        "current_plan": [],
        "completed_steps": [],
        "adaptation_history": [],
        "needs_replanning": False,
        "evaluation_result": None,
        "current_step_id": None,
        "pending_feedback": [],
        "feedback_responses": {"test_request_id": "User response"},
        "waiting_for_human": True,
        "current_feedback_request": {
            "request_id": "test_request_id",
            "agent_name": "timeline",
            "question_type": "clarification",
            "question_text": "Test question",
            "status": "pending"
        },
    }
    
    # Create graph to test human_feedback_wait node
    graph = create_analysis_graph(db=None, rag_service=None, document_processor=None)
    
    # The node should check for feedback and update state
    # This is tested through integration tests

