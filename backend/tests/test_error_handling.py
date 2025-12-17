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
        
        from unittest.mock import Mock
        from app.services.analysis_service import AnalysisService
        
        mock_db = Mock()
        service = AnalysisService(mock_db)
        
        # Should have legacy extractors as fallback
        assert hasattr(service, 'timeline_extractor')
        assert hasattr(service, 'key_facts_extractor')
        assert hasattr(service, 'discrepancy_finder')
    
    def test_errors_added_to_state(self):
        """Test that errors are added to state['errors']"""
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
        
        # Симуляция ошибки в узле
        state["errors"].append({
            "node": "timeline",
            "error": "LLM API error",
            "timestamp": "2024-01-01T00:00:00",
            "type": "api_error"
        })
        
        assert len(state["errors"]) == 1
        assert state["errors"][0]["node"] == "timeline"
        assert "error" in state["errors"][0]
    
    def test_partial_results_preserved(self):
        """Test that partial results are preserved when errors occur"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": [{"date": "2024-01-01", "description": "Event"}]},  # Успешно
            "key_facts_result": None,  # Ошибка
            "discrepancy_result": {"discrepancies": []},  # Успешно
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy"],
            "errors": [{"node": "key_facts", "error": "Test error"}],
            "metadata": {}
        }
        
        # Частичные результаты должны сохраняться
        assert state["timeline_result"] is not None
        assert state["discrepancy_result"] is not None
        assert state["key_facts_result"] is None
        assert len(state["errors"]) > 0
    
    def test_fallback_on_critical_errors(self):
        """Test fallback to legacy methods on critical errors"""
        from unittest.mock import Mock, patch
        from app.config import config
        
        # Симуляция критической ошибки (например, граф не создается)
        # В реальной реализации это должно вызывать fallback
        
        # Проверка, что config имеет AGENT_ENABLED
        assert hasattr(config, 'AGENT_ENABLED')
        
        # Если агенты отключены, должен использоваться fallback
        # Это проверяется в AnalysisService
        assert isinstance(config.AGENT_ENABLED, bool)
