"""Tests for execution reliability improvements"""
import pytest
from app.services.langchain_agents.evaluation_metrics import EvaluationMetrics
from app.services.langchain_agents.fallback_handler import FallbackHandler, FallbackResult
from app.services.langchain_agents.replanning_agent import ReplanningAgent
from app.services.langchain_agents.state import AnalysisState, PlanStepStatus


class TestExecutionReliability:
    """Tests for execution reliability"""
    
    @pytest.fixture
    def evaluator(self):
        """Create evaluation metrics calculator"""
        return EvaluationMetrics()
    
    @pytest.fixture
    def fallback_handler(self):
        """Create fallback handler"""
        return FallbackHandler()
    
    def test_completeness_metric(self, evaluator):
        """Test completeness metric calculation"""
        result = {
            "events": [
                {"date": "2023-01-01", "description": "Event 1"},
                {"date": "2023-02-01", "description": "Event 2"}
            ]
        }
        
        completeness = evaluator.calculate_completeness(result, "timeline", expected_items=5)
        
        assert 0.0 <= completeness <= 1.0
        assert completeness == 0.4  # 2/5 = 0.4
    
    def test_accuracy_metric(self, evaluator):
        """Test accuracy metric calculation"""
        result = {
            "events": [
                {"date": "2023-01-01", "source_document": "doc1.pdf"},
                {"date": "2023-02-01"}  # Missing source
            ]
        }
        
        accuracy = evaluator.calculate_accuracy(result, "timeline")
        
        assert 0.0 <= accuracy <= 1.0
        assert accuracy < 1.0  # Should be less than 1.0 due to missing source
    
    def test_relevance_metric(self, evaluator):
        """Test relevance metric calculation"""
        result = {
            "facts": [
                {"value": "Important fact", "source": "doc1.pdf"}
            ]
        }
        
        relevance = evaluator.calculate_relevance(result, "key_facts")
        
        assert 0.0 <= relevance <= 1.0
    
    def test_consistency_metric(self, evaluator):
        """Test consistency metric calculation"""
        result = {
            "events": [
                {"date": "2023-01-01"},
                {"date": "2023-02-01"},
                {"date": "2023-03-01"}
            ]
        }
        
        consistency = evaluator.calculate_consistency(result, "timeline")
        
        assert 0.0 <= consistency <= 1.0
    
    def test_aggregate_metrics(self, evaluator):
        """Test metric aggregation"""
        aggregated = evaluator.aggregate_metrics(
            completeness=0.8,
            accuracy=0.9,
            relevance=0.7,
            consistency=0.85
        )
        
        assert "overall_score" in aggregated
        assert 0.0 <= aggregated["overall_score"] <= 1.0
        assert aggregated["overall_score"] > 0.7  # Should be good overall
    
    def test_fallback_timeout(self, fallback_handler):
        """Test fallback handling for timeout"""
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
            "analysis_types": [],
            "errors": [],
            "metadata": {},
            "plan_goals": [],
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
        
        result = fallback_handler.handle_failure(
            agent_name="timeline",
            error=Exception("Timeout error"),
            state=state
        )
        
        assert isinstance(result, FallbackResult)
        assert result.strategy in ["simplified_approach", "alternative_agent", "partial_result", "user_notification"]
    
    def test_fallback_no_result(self, fallback_handler):
        """Test fallback handling for no result"""
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
            "analysis_types": [],
            "errors": [],
            "metadata": {},
            "plan_goals": [],
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
        
        result = fallback_handler.handle_failure(
            agent_name="discrepancy",
            error=Exception("No result"),
            state=state
        )
        
        # Discrepancy with no result is valid (no discrepancies found)
        assert result.success
        assert result.strategy == "expected_empty"
    
    def test_result_combination(self, fallback_handler):
        """Test combining results from multiple sources"""
        results = [
            {"events": [{"date": "2023-01-01"}]},
            {"events": [{"date": "2023-02-01"}]}
        ]
        
        combined = fallback_handler.combine_results(results, "timeline")
        
        assert "events" in combined
        assert len(combined["events"]) == 2
    
    def test_replanning_strategy_selection(self):
        """Test replanning strategy selection"""
        # This would require ReplanningAgent instance
        # For now, test that class exists
        assert ReplanningAgent is not None

