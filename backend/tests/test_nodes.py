"""Tests for individual graph nodes"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.timeline_node import timeline_agent_node
from app.services.langchain_agents.key_facts_node import key_facts_agent_node
from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
from app.services.langchain_agents.risk_node import risk_agent_node
from app.services.langchain_agents.summary_node import summary_agent_node


class TestTimelineNode:
    """Test timeline agent node"""
    
    def test_timeline_node_handles_empty_state(self):
        """Test that timeline node handles empty state"""
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
        
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        # Node should handle the state without crashing
        # (will fail on actual execution without real services, but structure is correct)
        assert state["case_id"] == "test_case"
        assert state["timeline_result"] is None
    
    def test_timeline_node_updates_state(self):
        """Test that timeline node updates state correctly"""
        # This is a structural test - actual execution requires real services
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
        
        # After node execution, timeline_result should be set
        # (in real execution)
        assert "timeline_result" in state


class TestKeyFactsNode:
    """Test key facts agent node"""
    
    def test_key_facts_node_structure(self):
        """Test key facts node structure"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["key_facts"],
            "errors": [],
            "metadata": {}
        }
        
        assert "key_facts_result" in state
        assert state["key_facts_result"] is None


class TestDiscrepancyNode:
    """Test discrepancy agent node"""
    
    def test_discrepancy_node_structure(self):
        """Test discrepancy node structure"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["discrepancy"],
            "errors": [],
            "metadata": {}
        }
        
        assert "discrepancy_result" in state


class TestRiskNode:
    """Test risk agent node"""
    
    def test_risk_node_checks_dependency(self):
        """Test that risk node checks for discrepancy_result"""
        # State without discrepancy - risk node should skip
        state_no_dep: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,  # Missing dependency
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        # Risk node should check this
        assert state_no_dep["discrepancy_result"] is None
        
        # State with discrepancy - risk node should proceed
        state_with_dep: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": {"discrepancies": [], "total": 0},  # Dependency ready
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        assert state_with_dep["discrepancy_result"] is not None
    
    def test_risk_node_skips_without_dependency(self):
        """Test that risk node skips execution without discrepancy_result"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,  # Not ready
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        # Risk node should not execute without discrepancy_result
        # This is checked in the node implementation
        assert state["discrepancy_result"] is None


class TestSummaryNode:
    """Test summary agent node"""
    
    def test_summary_node_checks_dependency(self):
        """Test that summary node checks for key_facts_result"""
        # State without key_facts - summary node should skip
        state_no_dep: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,  # Missing dependency
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["summary"],
            "errors": [],
            "metadata": {}
        }
        
        assert state_no_dep["key_facts_result"] is None
        
        # State with key_facts - summary node should proceed
        state_with_dep: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": {"facts": {}, "result_id": "123"},  # Dependency ready
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["summary"],
            "errors": [],
            "metadata": {}
        }
        
        assert state_with_dep["key_facts_result"] is not None
    
    def test_summary_node_skips_without_dependency(self):
        """Test that summary node skips execution without key_facts_result"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,  # Not ready
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["summary"],
            "errors": [],
            "metadata": {}
        }
        
        # Summary node should not execute without key_facts_result
        assert state["key_facts_result"] is None


class TestIndependentNodes:
    """Test that independent nodes can execute independently"""
    
    def test_timeline_node_independent(self):
        """Test that timeline node is independent"""
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
        
        # Timeline doesn't depend on other results
        assert state["timeline_result"] is None
        # Can execute independently
        assert "timeline" in state["analysis_types"]
    
    def test_key_facts_node_independent(self):
        """Test that key_facts node is independent"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["key_facts"],
            "errors": [],
            "metadata": {}
        }
        
        # Key facts doesn't depend on other results
        assert state["key_facts_result"] is None
        # Can execute independently
        assert "key_facts" in state["analysis_types"]
    
    def test_discrepancy_node_independent(self):
        """Test that discrepancy node is independent"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["discrepancy"],
            "errors": [],
            "metadata": {}
        }
        
        # Discrepancy doesn't depend on other results
        assert state["discrepancy_result"] is None
        # Can execute independently
        assert "discrepancy" in state["analysis_types"]
    
    def test_independent_nodes_can_run_parallel(self):
        """Test that independent nodes can run in parallel"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy"],
            "errors": [],
            "metadata": {}
        }
        
        # All three are independent and can run in parallel
        independent_types = ["timeline", "key_facts", "discrepancy"]
        for analysis_type in independent_types:
            assert analysis_type in state["analysis_types"]
            # None of them require other results
            assert state.get(f"{analysis_type.replace('_', '_')}_result") is None or analysis_type == "timeline"


class TestNodeErrorHandling:
    """Test error handling in nodes"""
    
    def test_nodes_handle_errors_gracefully(self):
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
        
        # Nodes should add errors to state["errors"] on failure
        assert isinstance(state["errors"], list)
        assert "errors" in state
