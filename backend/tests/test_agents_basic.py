"""Basic tests for LangChain agents components"""
import pytest
from typing import Dict, Any
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt, get_all_prompts
from app.services.langchain_agents.supervisor import route_to_agent, create_supervisor_agent
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor


class TestAnalysisState:
    """Test AnalysisState definition"""
    
    def test_state_definition(self):
        """Test that AnalysisState is properly defined"""
        # Check that we can create a state dict
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
        
        assert state["case_id"] == "test_case"
        assert state["analysis_types"] == ["timeline"]
        assert state["timeline_result"] is None
    
    def test_state_with_results(self):
        """Test state with results"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": [], "total_events": 0},
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline"],
            "errors": [],
            "metadata": {}
        }
        
        assert state["timeline_result"] is not None
        assert state["timeline_result"]["total_events"] == 0


class TestTools:
    """Test tools functionality"""
    
    def test_get_all_tools(self):
        """Test that all tools are available"""
        tools = get_all_tools()
        
        assert len(tools) > 0
        assert any(tool.name == "retrieve_documents_tool" for tool in tools)
        assert any(tool.name == "save_timeline_tool" for tool in tools)
        assert any(tool.name == "save_key_facts_tool" for tool in tools)
        assert any(tool.name == "save_discrepancy_tool" for tool in tools)
        assert any(tool.name == "save_risk_analysis_tool" for tool in tools)
        assert any(tool.name == "save_summary_tool" for tool in tools)
    
    def test_initialize_tools(self):
        """Test tools initialization"""
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        
        # Should not raise an error
        initialize_tools(rag_service, document_processor)


class TestPrompts:
    """Test prompts functionality"""
    
    def test_get_all_prompts(self):
        """Test that all prompts are available"""
        prompts = get_all_prompts()
        
        assert "supervisor" in prompts
        assert "timeline" in prompts
        assert "key_facts" in prompts
        assert "discrepancy" in prompts
        assert "risk" in prompts
        assert "summary" in prompts
    
    def test_get_agent_prompt(self):
        """Test getting individual prompts"""
        supervisor_prompt = get_agent_prompt("supervisor")
        assert len(supervisor_prompt) > 0
        assert "супервизор" in supervisor_prompt.lower() or "supervisor" in supervisor_prompt.lower()
        
        timeline_prompt = get_agent_prompt("timeline")
        assert len(timeline_prompt) > 0
        
        # Test invalid agent name
        invalid_prompt = get_agent_prompt("invalid_agent")
        assert invalid_prompt == ""


class TestSupervisor:
    """Test supervisor functionality"""
    
    def test_route_to_agent(self):
        """Test routing logic"""
        # Test with no results - should route to independent agents
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
        
        route = route_to_agent(state)
        assert route in ["timeline", "key_facts", "discrepancy"]
        
        # Test with timeline done
        state["timeline_result"] = {"events": []}
        route = route_to_agent(state)
        assert route in ["key_facts", "discrepancy"]
        
        # Test with key_facts done - should allow summary
        state["key_facts_result"] = {"facts": {}}
        route = route_to_agent(state)
        assert route in ["discrepancy", "summary"]
        
        # Test with discrepancy done - should allow risk
        state["discrepancy_result"] = {"discrepancies": []}
        route = route_to_agent(state)
        assert route in ["risk", "summary"]
        
        # Test all done
        state["risk_result"] = {"analysis": "test"}
        state["summary_result"] = {"summary": "test"}
        route = route_to_agent(state)
        assert route == "end"
    
    def test_create_supervisor_agent(self):
        """Test supervisor agent creation"""
        # Should not raise an error
        supervisor = create_supervisor_agent()
        assert supervisor is not None
