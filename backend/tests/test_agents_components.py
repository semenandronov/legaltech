"""Tests for basic agent components"""
import pytest
from typing import Dict, Any
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.tools import get_all_tools, initialize_tools
from app.services.langchain_agents.prompts import get_agent_prompt, get_all_prompts
from app.services.langchain_agents.supervisor import route_to_agent, create_supervisor_agent


class TestAnalysisState:
    """Test AnalysisState definition"""
    
    def test_state_structure(self):
        """Test that AnalysisState has all required fields"""
        # Create a sample state
        state: AnalysisState = {
            "case_id": "test_case_123",
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
        
        assert state["case_id"] == "test_case_123"
        assert state["analysis_types"] == ["timeline"]
        assert state["timeline_result"] is None
        assert isinstance(state["errors"], list)
        assert isinstance(state["metadata"], dict)
    
    def test_state_with_results(self):
        """Test state with results"""
        state: AnalysisState = {
            "case_id": "test_case_123",
            "messages": [],
            "timeline_result": {"events": [], "total_events": 0},
            "key_facts_result": {"facts": {}, "result_id": "123"},
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts"],
            "errors": [],
            "metadata": {}
        }
        
        assert state["timeline_result"] is not None
        assert state["key_facts_result"] is not None
        assert state["discrepancy_result"] is None


class TestTools:
    """Test tools functionality"""
    
    def test_get_all_tools(self):
        """Test that all tools are available"""
        tools = get_all_tools()
        
        assert len(tools) > 0
        # Check that we have expected tools
        tool_names = [tool.name for tool in tools]
        assert "retrieve_documents_tool" in tool_names
        assert "save_timeline_tool" in tool_names
        assert "save_key_facts_tool" in tool_names
        assert "save_discrepancy_tool" in tool_names
        assert "save_risk_analysis_tool" in tool_names
        assert "save_summary_tool" in tool_names
    
    def test_tools_have_descriptions(self):
        """Test that all tools have descriptions"""
        tools = get_all_tools()
        
        for tool in tools:
            assert hasattr(tool, 'description')
            assert tool.description is not None
            assert len(tool.description) > 0
    
    def test_initialize_tools(self):
        """Test tool initialization with services"""
        from app.services.rag_service import RAGService
        from app.services.document_processor import DocumentProcessor
        from app.services.langchain_agents.tools import initialize_tools
        
        # Mock services
        mock_rag = RAGService.__new__(RAGService)
        mock_doc_processor = DocumentProcessor.__new__(DocumentProcessor)
        
        # Initialize tools
        initialize_tools(mock_rag, mock_doc_processor)
        
        # Verify tools can be retrieved
        tools = get_all_tools()
        assert len(tools) > 0
    
    def test_retrieve_documents_tool_format(self):
        """Test that retrieve_documents_tool returns formatted data"""
        from app.services.langchain_agents.tools import retrieve_documents_tool
        
        # Check tool signature
        assert hasattr(retrieve_documents_tool, 'name')
        assert retrieve_documents_tool.name == "retrieve_documents_tool"
        
        # Check tool has correct parameters
        # Note: This is a structural test, actual execution requires initialized services
        assert callable(retrieve_documents_tool.func)
    
    def test_save_tools_format(self):
        """Test that save tools have correct format"""
        from app.services.langchain_agents.tools import (
            save_timeline_tool,
            save_key_facts_tool,
            save_discrepancy_tool,
            save_risk_analysis_tool,
            save_summary_tool
        )
        
        save_tools = [
            save_timeline_tool,
            save_key_facts_tool,
            save_discrepancy_tool,
            save_risk_analysis_tool,
            save_summary_tool
        ]
        
        for tool in save_tools:
            assert hasattr(tool, 'name')
            assert hasattr(tool, 'description')
            assert callable(tool.func)
    
    def test_tools_error_handling(self):
        """Test that tools handle errors gracefully"""
        from app.services.langchain_agents.tools import (
            retrieve_documents_tool,
            save_timeline_tool
        )
        
        # Test retrieve_documents_tool without initialization
        # Should raise ValueError
        try:
            result = retrieve_documents_tool.func("test query", "test_case", k=5)
            # If no error, check that it returns error message
            assert isinstance(result, str)
        except ValueError as e:
            assert "RAG service not initialized" in str(e)
        
        # Test save_timeline_tool with invalid data
        # Should return error message string
        result = save_timeline_tool.func("invalid json", "test_case")
        assert isinstance(result, str)
        # Should contain error indication
        assert "error" in result.lower() or "successfully" in result.lower()


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
        assert supervisor_prompt is not None
        assert len(supervisor_prompt) > 0
        assert "супервизор" in supervisor_prompt.lower() or "supervisor" in supervisor_prompt.lower()
        
        timeline_prompt = get_agent_prompt("timeline")
        assert timeline_prompt is not None
        assert len(timeline_prompt) > 0
    
    def test_prompts_content(self):
        """Test that prompts contain expected content"""
        prompts = get_all_prompts()
        
        # Check supervisor prompt
        assert "распределять" in prompts["supervisor"].lower() or "distribute" in prompts["supervisor"].lower()
        
        # Check timeline prompt
        assert "даты" in prompts["timeline"].lower() or "dates" in prompts["timeline"].lower()
        assert "события" in prompts["timeline"].lower() or "events" in prompts["timeline"].lower()
    
    def test_all_prompts_not_empty(self):
        """Test that all prompts are not empty"""
        prompts = get_all_prompts()
        
        for agent_name, prompt in prompts.items():
            assert prompt is not None, f"Prompt for {agent_name} is None"
            assert len(prompt.strip()) > 0, f"Prompt for {agent_name} is empty"
            assert len(prompt) > 50, f"Prompt for {agent_name} is too short (less than 50 chars)"
    
    def test_prompts_contain_instructions(self):
        """Test that prompts contain necessary instructions"""
        prompts = get_all_prompts()
        
        # Supervisor should mention agents
        assert any(word in prompts["supervisor"].lower() for word in ["timeline", "key_facts", "discrepancy", "risk", "summary"])
        
        # Timeline should mention dates/events
        timeline_lower = prompts["timeline"].lower()
        assert any(word in timeline_lower for word in ["даты", "dates", "события", "events", "timeline"])
        
        # Key facts should mention facts/extraction
        key_facts_lower = prompts["key_facts"].lower()
        assert any(word in key_facts_lower for word in ["факты", "facts", "извлечение", "extract"])
        
        # Discrepancy should mention contradictions
        discrepancy_lower = prompts["discrepancy"].lower()
        assert any(word in discrepancy_lower for word in ["противоречия", "contradiction", "несоответствия", "discrepancy"])
        
        # Risk should mention risks
        risk_lower = prompts["risk"].lower()
        assert any(word in risk_lower for word in ["риски", "risks", "риск", "risk"])
        
        # Summary should mention summary/resume
        summary_lower = prompts["summary"].lower()
        assert any(word in summary_lower for word in ["резюме", "summary", "краткое", "brief"])
    
    def test_prompts_match_agent_tasks(self):
        """Test that prompts match agent tasks"""
        prompts = get_all_prompts()
        
        # Each prompt should mention its tool usage
        assert "retrieve_documents_tool" in prompts["timeline"] or "retrieve" in prompts["timeline"].lower()
        assert "save_timeline_tool" in prompts["timeline"] or "save" in prompts["timeline"].lower()
        
        assert "retrieve_documents_tool" in prompts["key_facts"] or "retrieve" in prompts["key_facts"].lower()
        assert "save_key_facts_tool" in prompts["key_facts"] or "save" in prompts["key_facts"].lower()
        
        assert "retrieve_documents_tool" in prompts["discrepancy"] or "retrieve" in prompts["discrepancy"].lower()
        assert "save_discrepancy_tool" in prompts["discrepancy"] or "save" in prompts["discrepancy"].lower()
        
        # Risk should mention using discrepancy results
        assert "discrepancy" in prompts["risk"].lower() or "противоречия" in prompts["risk"].lower()
        
        # Summary should mention using key_facts results
        assert "key_facts" in prompts["summary"].lower() or "факты" in prompts["summary"].lower()


class TestSupervisor:
    """Test supervisor functionality"""
    
    def test_route_to_agent_independent(self):
        """Test routing for independent agents"""
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
        
        route = route_to_agent(state)
        assert route == "timeline"
    
    def test_route_to_agent_dependent(self):
        """Test routing for dependent agents"""
        # Test risk agent - needs discrepancy
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": {"discrepancies": [], "total": 0},
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state)
        assert route == "risk"
    
    def test_route_to_agent_dependency_not_ready(self):
        """Test routing when dependency is not ready"""
        # Test risk agent without discrepancy
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
        
        route = route_to_agent(state)
        # Should route to supervisor to wait or to another available agent
        assert route in ["supervisor", "end"]
    
    def test_route_to_agent_all_completed(self):
        """Test routing when all analyses are completed"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": []},
            "key_facts_result": {"facts": {}},
            "discrepancy_result": {"discrepancies": []},
            "risk_result": {"analysis": "test"},
            "summary_result": {"summary": "test"},
            "analysis_types": ["timeline", "key_facts", "discrepancy", "risk", "summary"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state)
        assert route == "end"
    
    def test_route_to_agent_parallel(self):
        """Test routing for parallel independent agents"""
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
        
        # First call should route to one of the independent agents
        route = route_to_agent(state)
        assert route in ["timeline", "key_facts", "discrepancy"]
        
        # After one completes, should route to next
        state["timeline_result"] = {"events": []}
        route = route_to_agent(state)
        assert route in ["key_facts", "discrepancy"]
