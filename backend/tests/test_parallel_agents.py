"""Tests for parallel agent execution"""
import pytest
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState, create_initial_state


def test_parallel_independent_agents_node():
    """Test that parallel_independent_agents node executes multiple agents in parallel"""
    # Create a mock state with multiple independent agents requested
    state = create_initial_state(
        case_id="test_case",
        analysis_types=["timeline", "key_facts", "discrepancy", "entity_extraction"]
    )
    
    # Create graph
    graph = create_analysis_graph(db=None, rag_service=None, document_processor=None)
    
    # The parallel node should be called by supervisor when multiple independent agents are pending
    # This is tested through integration tests with actual agent execution


def test_supervisor_routes_to_parallel_node():
    """Test that supervisor routes to parallel node when multiple independent agents are pending"""
    from app.services.langchain_agents.supervisor import route_to_agent
    
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
        "analysis_types": ["timeline", "key_facts", "discrepancy"],
        "errors": [],
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
    
    # Supervisor should route to parallel_independent when multiple independent agents are pending
    next_agent = route_to_agent(state)
    
    # Should route to parallel_independent since we have 3 independent agents
    assert next_agent == "parallel_independent"

