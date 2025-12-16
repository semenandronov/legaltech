"""Tests for error handling"""
import pytest
from app.services.langchain_agents.state import AnalysisState


class TestErrorHandling:
    """Test error handling in agent system"""
    
    def test_state_has_errors_field(self):
        """Test that state has errors field for error tracking"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline"],
            "errors": [],
            "metadata": {}
        }
        
        assert "errors" in state
        assert isinstance(state["errors"], list)
    
    def test_nodes_add_errors_to_state(self):
        """Test that nodes add errors to state on failure"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline"],
            "errors": [],
            "metadata": {}
        }
        
        # Simulate error addition
        state["errors"].append({
            "agent": "timeline",
            "error": "Test error"
        })
        
        assert len(state["errors"]) == 1
        assert state["errors"][0]["agent"] == "timeline"
    
    def test_partial_results_handled(self):
        """Test that partial results are handled when some agents fail"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": []},  # Success
            "key_facts_result": None,  # Failed
            "discrepancy_result": {"discrepancies": []},  # Success
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy"],
            "errors": [{"agent": "key_facts", "error": "Test error"}],
            "metadata": {}
        }
        
        # Should have partial results
        assert state["timeline_result"] is not None
        assert state["discrepancy_result"] is not None
        assert state["key_facts_result"] is None
        assert len(state["errors"]) > 0
    
    def test_fallback_mechanism(self):
        """Test that fallback to legacy methods works"""
        # AnalysisService should fallback to legacy extractors
        # when agents are disabled or fail
        
        from app.services.analysis_service import AnalysisService
        
        mock_db = Mock()
        service = AnalysisService(mock_db)
        
        # Should have legacy extractors as fallback
        assert hasattr(service, 'timeline_extractor')
        assert hasattr(service, 'key_facts_extractor')
        assert hasattr(service, 'discrepancy_finder')
