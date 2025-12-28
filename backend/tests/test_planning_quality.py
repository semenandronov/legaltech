"""Tests for planning quality improvements"""
import pytest
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.planning_validator import PlanningValidator
from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
from app.services.rag_service import RAGService
from app.services.document_processor import DocumentProcessor


class TestPlanningQuality:
    """Tests for planning quality"""
    
    @pytest.fixture
    def planning_agent(self):
        """Create planning agent for testing"""
        rag_service = RAGService()
        document_processor = DocumentProcessor()
        return PlanningAgent(rag_service=rag_service, document_processor=document_processor)
    
    @pytest.fixture
    def validator(self):
        """Create validator for testing"""
        return PlanningValidator()
    
    def test_autonomous_document_analysis(self, planning_agent):
        """Test autonomous document analysis for planning"""
        # This would require a test case with documents
        # For now, test that method exists and doesn't crash
        case_id = "test_case"
        result = planning_agent.analyze_documents_for_planning(case_id)
        
        assert "case_type" in result
        assert "suggested_analyses" in result
        assert isinstance(result["suggested_analyses"], list)
    
    def test_multi_level_planning(self, planning_agent):
        """Test multi-level planning structure"""
        user_task = "Найди все риски в документах"
        case_id = "test_case"
        
        plan = planning_agent.plan_analysis(user_task, case_id)
        
        # Check multi-level structure
        assert "goals" in plan or "analysis_types" in plan
        assert "reasoning" in plan
        assert "confidence" in plan
        
        # If multi-level, check steps
        if "steps" in plan:
            assert isinstance(plan["steps"], list)
            if plan["steps"]:
                step = plan["steps"][0]
                assert "agent_name" in step
                assert "reasoning" in step
    
    def test_plan_validation(self, validator):
        """Test plan validation"""
        plan = {
            "analysis_types": ["risk"],
            "steps": [
                {
                    "step_id": "risk_1",
                    "agent_name": "risk",
                    "dependencies": ["discrepancy"]
                }
            ]
        }
        
        result = validator.validate_plan(plan, "test_case")
        
        # Risk requires discrepancy, so validation should find issue
        assert len(result.issues) > 0 or "discrepancy" in plan.get("analysis_types", [])
        assert result.optimized_plan is not None
    
    def test_dependency_validation(self, validator):
        """Test dependency validation"""
        # Plan with missing dependency
        plan = {
            "analysis_types": ["risk"],  # Missing discrepancy
            "steps": []
        }
        
        result = validator.validate_plan(plan, "test_case")
        
        # Should detect missing dependency
        assert not result.is_valid or "discrepancy" in result.optimized_plan.get("analysis_types", [])
    
    def test_plan_optimization(self, validator):
        """Test plan optimization"""
        plan = {
            "analysis_types": ["timeline", "key_facts", "discrepancy", "risk"],
            "steps": []
        }
        
        result = validator.validate_plan(plan, "test_case")
        
        # Should optimize order (independent first, then dependent)
        optimized = result.optimized_plan
        if optimized and "analysis_types" in optimized:
            types = optimized["analysis_types"]
            # Risk should come after discrepancy
            if "risk" in types and "discrepancy" in types:
                risk_idx = types.index("risk")
                discrepancy_idx = types.index("discrepancy")
                assert discrepancy_idx < risk_idx
    
    def test_tool_selection(self, planning_agent):
        """Test tool selection in planning"""
        user_task = "Найди противоречия и проверь case law"
        case_id = "test_case"
        
        plan = planning_agent.plan_analysis(user_task, case_id)
        
        # Check if steps have tools
        if "steps" in plan:
            for step in plan["steps"]:
                if step.get("agent_name") == "discrepancy":
                    # Discrepancy should have retrieve_documents and possibly web_search
                    tools = step.get("tools", [])
                    assert "retrieve_documents" in tools
                    # If case law mentioned, should have web_search
                    if "case law" in user_task.lower() or "прецедент" in user_task.lower():
                        assert "web_search" in tools or len(tools) > 1
    
    def test_alternative_plans(self, planning_agent):
        """Test generation of alternative plans"""
        user_task = "Сложная задача с множеством анализов"
        case_id = "test_case"
        
        plan = planning_agent.plan_analysis(user_task, case_id)
        
        # For complex tasks, should have alternative plans
        if len(plan.get("analysis_types", [])) > 3:
            assert "alternative_plans" in plan or plan.get("confidence", 1.0) < 0.8

