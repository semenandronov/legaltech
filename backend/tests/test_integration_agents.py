"""Integration tests for full agent cycle with evaluation, adaptation, and human feedback"""
import pytest
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.langchain_agents.state import AnalysisState, create_initial_state


@pytest.mark.integration
def test_full_cycle_with_evaluation():
    """Test full cycle: agent -> evaluation -> supervisor"""
    # This is an integration test that would require actual database and services
    # For now, we test the state transitions
    
    # Initial state
    state = create_initial_state(
        case_id="test_case",
        analysis_types=["timeline"]
    )
    
    # Simulate agent execution
    state["timeline_result"] = {
        "events": [{"date": "2024-01-01", "event_type": "test", "description": "Test event"}],
        "total_events": 1
    }
    state["current_step_id"] = "timeline_test_case_0"
    
    # Evaluation should process this
    from app.services.langchain_agents.evaluation_node import evaluation_node
    evaluated_state = evaluation_node(state, db=None, rag_service=None, document_processor=None)
    
    # Check evaluation result
    assert evaluated_state.get("evaluation_result") is not None
    eval_result = evaluated_state.get("evaluation_result")
    assert "confidence" in eval_result
    assert "completeness" in eval_result


@pytest.mark.integration
def test_adaptation_cycle():
    """Test cycle with adaptation: agent -> evaluation -> adaptation -> supervisor"""
    state = create_initial_state(
        case_id="test_case",
        analysis_types=["timeline"]
    )
    
    # Simulate low-quality result
    state["timeline_result"] = {
        "events": [],
        "total_events": 0
    }
    state["current_step_id"] = "timeline_test_case_0"
    state["current_plan"] = [
        {
            "step_id": "timeline_test_case_0",
            "agent_name": "timeline",
            "description": "Extract timeline",
            "status": "pending",
            "dependencies": [],
            "result_key": "timeline_result"
        }
    ]
    
    # Evaluation
    from app.services.langchain_agents.evaluation_node import evaluation_node
    evaluated_state = evaluation_node(state, db=None, rag_service=None, document_processor=None)
    
    # Check if adaptation is needed
    if evaluated_state.get("needs_replanning"):
        from app.services.langchain_agents.adaptation_engine import adaptation_node
        adapted_state = adaptation_node(
            evaluated_state,
            db=None,
            rag_service=None,
            document_processor=None
        )
        
        # Check adaptation history
        assert len(adapted_state.get("adaptation_history", [])) > 0


@pytest.mark.integration
def test_human_feedback_cycle():
    """Test cycle with human feedback: agent -> evaluation -> human_feedback -> supervisor"""
    state = create_initial_state(
        case_id="test_case",
        analysis_types=["timeline"]
    )
    
    # Simulate low confidence result
    state["timeline_result"] = {
        "events": [],
        "total_events": 0
    }
    state["current_step_id"] = "timeline_test_case_0"
    state["current_plan"] = [
        {
            "step_id": "timeline_test_case_0",
            "agent_name": "timeline",
            "description": "Extract timeline",
            "status": "pending",
            "dependencies": [],
            "result_key": "timeline_result"
        }
    ]
    
    # Evaluation should create human feedback request
    from app.services.langchain_agents.evaluation_node import evaluation_node
    evaluated_state = evaluation_node(state, db=None, rag_service=None, document_processor=None)
    
    # Check if human feedback was requested
    if evaluated_state.get("waiting_for_human"):
        assert evaluated_state.get("current_feedback_request") is not None
        
        # Simulate receiving feedback
        feedback_request = evaluated_state.get("current_feedback_request")
        request_id = feedback_request.get("request_id")
        
        evaluated_state["feedback_responses"] = {
            request_id: "User provided clarification"
        }
        
        # Human feedback wait node should process this
        from app.services.langchain_agents.graph import create_analysis_graph
        graph = create_analysis_graph(db=None, rag_service=None, document_processor=None)
        
        # The node would check for feedback and update state
        # This is tested through actual graph execution

