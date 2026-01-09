"""Integration tests for refactored agent system"""
import pytest
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.langchain_agents.state import create_initial_state
from app.services.langchain_agents.component_factory import ComponentFactory
from app.services.langchain_agents.unified_error_handler import UnifiedErrorHandler, ErrorType


@pytest.fixture
def mock_db():
    """Mock database session"""
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock(
        id="test_case",
        user_id="test_user",
        num_documents=5,
        file_names=["doc1.pdf", "doc2.pdf"]
    )
    return db


@pytest.fixture
def mock_rag_service():
    """Mock RAG service"""
    return Mock()


@pytest.fixture
def mock_document_processor():
    """Mock document processor"""
    return Mock()


@pytest.fixture
def coordinator(mock_db, mock_rag_service, mock_document_processor):
    """Create agent coordinator with mocked dependencies"""
    with patch('app.services.langchain_agents.coordinator.create_analysis_graph') as mock_graph:
        mock_graph.return_value = Mock()
        with patch('app.services.langchain_agents.component_factory.ComponentFactory.create_all_components') as mock_components:
            mock_components.return_value = {
                'advanced_planning_agent': None,
                'planning_agent': None,
                'feedback_service': Mock(),
                'fallback_handler': Mock(),
                'metrics_collector': Mock(),
                'subagent_manager': None,
                'context_manager': None,
                'learning_service': None
            }
            coord = AgentCoordinator(
                db=mock_db,
                rag_service=mock_rag_service,
                document_processor=mock_document_processor
            )
            return coord


class TestComponentFactory:
    """Tests for ComponentFactory"""
    
    def test_create_required_component_success(self):
        """Test successful creation of required component"""
        def factory():
            return {"test": "component"}
        
        result = ComponentFactory.create_required_component(
            "TestComponent",
            factory,
            "Test error"
        )
        assert result == {"test": "component"}
    
    def test_create_required_component_failure(self):
        """Test failure of required component raises error"""
        def factory():
            raise ValueError("Test error")
        
        with pytest.raises(RuntimeError, match="Test error"):
            ComponentFactory.create_required_component(
                "TestComponent",
                factory,
                "Test error"
            )
    
    def test_create_optional_component_success(self):
        """Test successful creation of optional component"""
        def factory():
            return {"test": "component"}
        
        result = ComponentFactory.create_optional_component(
            "TestComponent",
            factory
        )
        assert result == {"test": "component"}
    
    def test_create_optional_component_failure(self):
        """Test failure of optional component returns None"""
        def factory():
            raise ValueError("Test error")
        
        result = ComponentFactory.create_optional_component(
            "TestComponent",
            factory
        )
        assert result is None


class TestUnifiedErrorHandler:
    """Tests for UnifiedErrorHandler"""
    
    def test_classify_timeout_error(self):
        """Test classification of timeout errors"""
        handler = UnifiedErrorHandler()
        error = TimeoutError("Operation timed out")
        
        error_type = handler.classify_error(error)
        assert error_type == ErrorType.TIMEOUT
    
    def test_classify_tool_error(self):
        """Test classification of tool errors"""
        handler = UnifiedErrorHandler()
        error = NotImplementedError("bind_tools not supported")
        
        error_type = handler.classify_error(error)
        assert error_type == ErrorType.TOOL_ERROR
    
    def test_select_retry_strategy(self):
        """Test selection of retry strategy for timeout"""
        handler = UnifiedErrorHandler()
        strategy = handler.select_strategy(ErrorType.TIMEOUT, "timeline")
        
        from app.services.langchain_agents.unified_error_handler import ErrorStrategy
        assert strategy == ErrorStrategy.RETRY
    
    def test_handle_agent_error_with_retry(self):
        """Test error handling with retry strategy"""
        handler = UnifiedErrorHandler(max_retries=3)
        error = TimeoutError("Operation timed out")
        context = {"case_id": "test_case", "agent_name": "timeline"}
        
        result = handler.handle_agent_error("timeline", error, context, retry_count=0)
        
        assert result.should_retry is True
        assert result.retry_count == 1
        assert result.retry_after is not None


class TestAgentCoordinatorInitialization:
    """Tests for AgentCoordinator initialization"""
    
    def test_coordinator_initialization_success(self, coordinator):
        """Test successful coordinator initialization"""
        assert coordinator.db is not None
        assert coordinator.graph is not None
    
    def test_coordinator_initialization_components(self, coordinator):
        """Test that all components are initialized"""
        # Components should be set (even if None for optional ones)
        assert hasattr(coordinator, 'planning_agent')
        assert hasattr(coordinator, 'feedback_service')
        assert hasattr(coordinator, 'fallback_handler')


class TestAgentExecutionFlow:
    """Tests for agent execution flow"""
    
    def test_run_analysis_validation(self, coordinator):
        """Test input validation in run_analysis"""
        # Test empty case_id
        with pytest.raises(ValueError, match="case_id must be a non-empty string"):
            coordinator.run_analysis("", ["timeline"])
        
        # Test empty analysis_types
        with pytest.raises(ValueError, match="analysis_types must be a non-empty list"):
            coordinator.run_analysis("test_case", [])
        
        # Test invalid analysis type
        with pytest.raises(ValueError, match="Invalid analysis types"):
            coordinator.run_analysis("test_case", ["invalid_type"])
    
    @patch('app.services.langchain_agents.coordinator.create_initial_state')
    def test_run_analysis_state_creation(self, mock_state, coordinator):
        """Test state creation in run_analysis"""
        mock_state.return_value = {
            "case_id": "test_case",
            "analysis_types": ["timeline"],
            "messages": [],
            "errors": []
        }
        
        coordinator.graph.stream = Mock(return_value=iter([
            {"timeline": {"timeline_result": {"events": []}}}
        ]))
        coordinator.graph.get_state = Mock(return_value=Mock(values={
            "case_id": "test_case",
            "timeline_result": {"events": []},
            "errors": []
        }))
        
        result = coordinator.run_analysis("test_case", ["timeline"])
        
        assert result["case_id"] == "test_case"
        mock_state.assert_called_once()


class TestErrorHandlingIntegration:
    """Integration tests for error handling"""
    
    def test_error_propagation(self, coordinator):
        """Test that errors are properly propagated"""
        coordinator.graph.stream = Mock(side_effect=Exception("Test error"))
        
        result = coordinator.run_analysis("test_case", ["timeline"])
        
        assert "errors" in result
        assert len(result["errors"]) > 0
        assert result["timeline"] is None


class TestParallelExecution:
    """Tests for parallel execution optimization"""
    
    def test_parallel_agents_detection(self):
        """Test that independent agents are detected correctly"""
        from app.services.langchain_agents.supervisor import route_to_agent
        from app.services.langchain_agents.state import create_initial_state
        
        state = create_initial_state(
            case_id="test_case",
            analysis_types=["timeline", "key_facts", "discrepancy"]
        )
        
        # Should route to parallel_independent when multiple independent agents
        route = route_to_agent(state)
        assert route == "parallel_independent"
    
    def test_dependent_agents_wait(self):
        """Test that dependent agents wait for dependencies"""
        from app.services.langchain_agents.supervisor import route_to_agent
        from app.services.langchain_agents.state import create_initial_state
        
        state = create_initial_state(
            case_id="test_case",
            analysis_types=["risk"]
        )
        # risk requires discrepancy, which is not completed
        # Should wait (return "supervisor")
        route = route_to_agent(state)
        assert route == "supervisor"  # Waiting for dependency















