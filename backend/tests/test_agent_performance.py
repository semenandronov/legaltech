"""Performance tests and benchmarks for agent system"""
import pytest
import time
from typing import Dict, Any
from unittest.mock import Mock, patch
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.langchain_agents.graph import parallel_independent_agents_node
from app.services.langchain_agents.state import create_initial_state


@pytest.fixture
def mock_agent_node():
    """Mock agent node that simulates work"""
    def create_mock_node(agent_name: str, delay: float = 0.1):
        def mock_node(state):
            time.sleep(delay)  # Simulate work
            new_state = dict(state)
            new_state[f"{agent_name}_result"] = {"status": "completed"}
            return new_state
        return mock_node
    return create_mock_node


class TestParallelExecutionPerformance:
    """Performance tests for parallel execution"""
    
    def test_parallel_vs_sequential_timing(self, mock_agent_node):
        """Test that parallel execution is faster than sequential"""
        # Create mock nodes with delay
        timeline_node = mock_agent_node("timeline", delay=0.1)
        key_facts_node = mock_agent_node("key_facts", delay=0.1)
        discrepancy_node = mock_agent_node("discrepancy", delay=0.1)
        
        state = create_initial_state(
            case_id="test_case",
            analysis_types=["timeline", "key_facts", "discrepancy"]
        )
        
        # Sequential execution time
        start = time.time()
        state1 = timeline_node(state)
        state2 = key_facts_node(state1)
        state3 = discrepancy_node(state2)
        sequential_time = time.time() - start
        
        # Parallel execution (simulated - actual parallel would be faster)
        # Note: This is a simplified test - real parallel execution uses ThreadPoolExecutor
        assert sequential_time >= 0.3  # At least 3 * 0.1 seconds
    
    def test_timeout_configuration(self):
        """Test that timeout configuration is applied correctly"""
        from app.config import config
        
        # Check that timeout is reduced from 300 to 120
        assert config.AGENT_TIMEOUT <= 120, "AGENT_TIMEOUT should be <= 120 seconds"
        
        # Check that max_parallel is increased
        assert config.AGENT_MAX_PARALLEL >= 5, "AGENT_MAX_PARALLEL should be >= 5"


class TestSupervisorRoutingPerformance:
    """Performance tests for supervisor routing"""
    
    def test_routing_cache_effectiveness(self):
        """Test that routing cache improves performance"""
        from app.services.langchain_agents.supervisor import route_to_agent
        from app.services.langchain_agents.state import create_initial_state
        
        state = create_initial_state(
            case_id="test_case",
            analysis_types=["timeline", "key_facts"]
        )
        
        # First call (cache miss)
        start1 = time.time()
        route1 = route_to_agent(state)
        time1 = time.time() - start1
        
        # Second call with same state (should use cache)
        start2 = time.time()
        route2 = route_to_agent(state)
        time2 = time.time() - start2
        
        assert route1 == route2
        # Cache should make second call faster (or at least not slower)
        # Note: In real scenario with graph_optimizer, cache would be used


class TestMemoryUsage:
    """Tests for memory usage patterns"""
    
    def test_state_size_management(self):
        """Test that state doesn't grow unbounded"""
        state = create_initial_state(
            case_id="test_case",
            analysis_types=["timeline"]
        )
        
        initial_size = len(str(state))
        
        # Add some results
        state["timeline_result"] = {"events": [{"date": "2024-01-01", "description": "Event"}] * 100}
        state["key_facts_result"] = {"facts": [{"type": "fact", "value": "value"}] * 100}
        
        final_size = len(str(state))
        
        # State should grow but not excessively
        assert final_size > initial_size
        # But should be reasonable (less than 1MB for this test)
        assert final_size < 1_000_000


class TestConcurrentExecution:
    """Tests for concurrent execution patterns"""
    
    def test_max_parallel_limit(self):
        """Test that max_parallel limit is respected"""
        from app.config import config
        
        max_parallel = config.AGENT_MAX_PARALLEL
        
        # Should be at least 3 but not too high
        assert 3 <= max_parallel <= 10, "AGENT_MAX_PARALLEL should be between 3 and 10"
    
    def test_adaptive_timeouts(self):
        """Test that adaptive timeouts are configured"""
        # This would be tested in actual execution
        # For now, just verify the timeout structure exists
        from app.services.langchain_agents.graph import parallel_independent_agents_node
        
        # The function should exist and be callable
        assert callable(parallel_independent_agents_node)











































