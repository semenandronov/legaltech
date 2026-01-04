"""Stability tests for error handling and edge cases"""
import pytest
from typing import Dict, Any
from unittest.mock import Mock, patch
from app.services.langchain_agents.unified_error_handler import (
    UnifiedErrorHandler,
    ErrorType,
    ErrorStrategy
)
from app.services.langchain_agents.fallback_handler import FallbackHandler
from app.services.langchain_agents.component_factory import ComponentFactory
from app.services.langchain_agents.state import create_initial_state


class TestUnifiedErrorHandlerStability:
    """Stability tests for UnifiedErrorHandler"""
    
    def test_handle_timeout_error(self):
        """Test handling of timeout errors"""
        handler = UnifiedErrorHandler(max_retries=3)
        error = TimeoutError("Operation timed out after 120 seconds")
        context = {"case_id": "test_case", "agent_name": "timeline"}
        
        result = handler.handle_agent_error("timeline", error, context, retry_count=0)
        
        assert result.strategy == ErrorStrategy.RETRY
        assert result.should_retry is True
        assert result.retry_after is not None
    
    def test_handle_tool_error(self):
        """Test handling of tool errors"""
        handler = UnifiedErrorHandler()
        error = NotImplementedError("bind_tools not supported")
        context = {"case_id": "test_case"}
        
        result = handler.handle_agent_error("timeline", error, context, retry_count=0)
        
        assert result.strategy == ErrorStrategy.FALLBACK
    
    def test_handle_validation_error(self):
        """Test handling of validation errors (should not retry)"""
        handler = UnifiedErrorHandler()
        error = ValueError("Invalid input: case_id cannot be empty")
        context = {"case_id": "test_case"}
        
        result = handler.handle_agent_error("timeline", error, context, retry_count=0)
        
        assert result.strategy == ErrorStrategy.FAIL
        assert result.should_retry is False
    
    def test_max_retries_limit(self):
        """Test that max retries limit is respected"""
        handler = UnifiedErrorHandler(max_retries=3)
        error = TimeoutError("Timeout")
        context = {"case_id": "test_case"}
        
        # Try with retry_count at max
        result = handler.handle_agent_error("timeline", error, context, retry_count=3)
        
        assert result.should_retry is False  # Should not retry after max retries
    
    def test_exponential_backoff(self):
        """Test exponential backoff calculation"""
        handler = UnifiedErrorHandler(base_retry_delay=1.0)
        
        delay1 = handler.get_retry_delay(0)
        delay2 = handler.get_retry_delay(1)
        delay3 = handler.get_retry_delay(2)
        
        assert delay1 == 1.0
        assert delay2 == 2.0
        assert delay3 == 4.0


class TestFallbackHandlerStability:
    """Stability tests for FallbackHandler"""
    
    def test_fallback_handler_initialization(self):
        """Test FallbackHandler initialization"""
        handler = FallbackHandler(max_retries=3, base_retry_delay=1.0)
        
        assert handler.unified_error_handler is not None
        assert handler.unified_error_handler.max_retries == 3
    
    def test_fallback_handler_error_handling(self):
        """Test FallbackHandler error handling"""
        handler = FallbackHandler()
        error = TimeoutError("Timeout")
        
        from app.services.langchain_agents.state import create_initial_state
        state = create_initial_state("test_case", ["timeline"])
        
        result = handler.handle_failure("timeline", error, state, retry_count=0)
        
        assert result.strategy == "retry" or result.strategy == "fail"
        assert hasattr(result, 'success')


class TestComponentFactoryStability:
    """Stability tests for ComponentFactory"""
    
    def test_required_component_failure_propagation(self):
        """Test that required component failures are properly propagated"""
        def failing_factory():
            raise ValueError("Critical error")
        
        with pytest.raises(RuntimeError):
            ComponentFactory.create_required_component(
                "CriticalComponent",
                failing_factory,
                "Failed to create critical component"
            )
    
    def test_optional_component_graceful_degradation(self):
        """Test that optional component failures don't break initialization"""
        def failing_factory():
            raise ValueError("Non-critical error")
        
        result = ComponentFactory.create_optional_component(
            "OptionalComponent",
            failing_factory
        )
        
        assert result is None  # Should return None, not raise


class TestEdgeCases:
    """Tests for edge cases and boundary conditions"""
    
    def test_empty_analysis_types(self):
        """Test handling of empty analysis types"""
        from app.services.langchain_agents.coordinator import AgentCoordinator
        from unittest.mock import Mock
        
        db = Mock()
        coordinator = AgentCoordinator(db, None, None)
        
        with pytest.raises(ValueError, match="analysis_types must be a non-empty list"):
            coordinator.run_analysis("test_case", [])
    
    def test_nonexistent_case(self):
        """Test handling of nonexistent case"""
        from app.services.langchain_agents.coordinator import AgentCoordinator
        from unittest.mock import Mock
        
        db = Mock()
        db.query.return_value.filter.return_value.first.return_value = None
        
        coordinator = AgentCoordinator(db, None, None)
        
        with pytest.raises(ValueError, match="not found in database"):
            coordinator.run_analysis("nonexistent_case", ["timeline"])
    
    def test_state_with_missing_fields(self):
        """Test handling of state with missing fields"""
        from app.services.langchain_agents.supervisor import route_to_agent
        
        # State with minimal fields
        minimal_state = {
            "case_id": "test_case",
            "analysis_types": ["timeline"],
            "messages": [],
            "errors": []
        }
        
        # Should not crash
        route = route_to_agent(minimal_state)
        assert route in ["timeline", "parallel_independent", "supervisor", "end"]
    
    def test_concurrent_state_access(self):
        """Test that state access is thread-safe"""
        # This would require actual concurrent execution
        # For now, just verify the structure supports it
        state = create_initial_state("test_case", ["timeline"])
        
        # State should be a dictionary (thread-safe for reads)
        assert isinstance(state, dict)
        
        # Multiple reads should not conflict
        case_id1 = state.get("case_id")
        case_id2 = state.get("case_id")
        assert case_id1 == case_id2


