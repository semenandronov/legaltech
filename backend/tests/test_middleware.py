"""Unit tests for middleware system"""
import pytest
from unittest.mock import Mock, MagicMock
from app.services.langchain_agents.middleware import (
    NodeMiddleware,
    LoggingMiddleware,
    MonitoringMiddleware,
    MiddlewareChain
)
from app.services.langchain_agents.state import AnalysisState


class TestNodeMiddleware:
    """Тесты для базового NodeMiddleware"""
    
    def test_before_execution_default(self):
        """Тест что before_execution возвращает state без изменений"""
        middleware = NodeMiddleware()
        state = {"case_id": "test", "messages": []}
        
        result = middleware.before_execution(state, "test_node")
        
        assert result == state
    
    def test_after_execution_default(self):
        """Тест что after_execution возвращает result_state"""
        middleware = NodeMiddleware()
        state = {"case_id": "test"}
        result_state = {"case_id": "test", "completed": True}
        
        result = middleware.after_execution(state, "test_node", result_state)
        
        assert result == result_state
    
    def test_on_error_default(self):
        """Тест что on_error возвращает None по умолчанию"""
        middleware = NodeMiddleware()
        state = {"case_id": "test"}
        error = Exception("Test error")
        
        result = middleware.on_error(state, "test_node", error)
        
        assert result is None


class TestLoggingMiddleware:
    """Тесты для LoggingMiddleware"""
    
    def test_before_execution_logs(self, caplog):
        """Тест что before_execution логирует"""
        import logging
        caplog.set_level(logging.INFO)
        
        middleware = LoggingMiddleware()
        state = {"case_id": "test-case"}
        
        middleware.before_execution(state, "test_node")
        
        assert "Before test_node execution" in caplog.text
        assert "test-case" in caplog.text
    
    def test_after_execution_logs(self, caplog):
        """Тест что after_execution логирует"""
        import logging
        caplog.set_level(logging.INFO)
        
        middleware = LoggingMiddleware()
        state = {"case_id": "test-case"}
        result_state = {"case_id": "test-case", "completed": True}
        
        middleware.after_execution(state, "test_node", result_state)
        
        assert "After test_node execution" in caplog.text
    
    def test_on_error_logs(self, caplog):
        """Тест что on_error логирует ошибку"""
        import logging
        caplog.set_level(logging.ERROR)
        
        middleware = LoggingMiddleware()
        state = {"case_id": "test-case"}
        error = Exception("Test error")
        
        middleware.on_error(state, "test_node", error)
        
        assert "Error in test_node" in caplog.text
        assert "Test error" in caplog.text


class TestMonitoringMiddleware:
    """Тесты для MonitoringMiddleware"""
    
    @patch('app.services.langchain_agents.middleware.get_graph_monitor')
    def test_before_execution_starts_monitoring(self, mock_get_monitor):
        """Тест что before_execution запускает мониторинг"""
        mock_monitor = Mock()
        mock_get_monitor.return_value = mock_monitor
        
        middleware = MonitoringMiddleware()
        state = {"case_id": "test-case"}
        
        middleware.before_execution(state, "test_node")
        
        mock_monitor.start_node_execution.assert_called_once_with("test-case", "test_node")
    
    @patch('app.services.langchain_agents.middleware.get_graph_monitor')
    def test_after_execution_ends_monitoring(self, mock_get_monitor):
        """Тест что after_execution завершает мониторинг"""
        mock_monitor = Mock()
        mock_get_monitor.return_value = mock_monitor
        
        middleware = MonitoringMiddleware()
        state = {"case_id": "test-case"}
        result_state = {"case_id": "test-case"}
        
        middleware.after_execution(state, "test_node", result_state)
        
        mock_monitor.end_node_execution.assert_called_once_with("test-case", "test_node")


class TestMiddlewareChain:
    """Тесты для MiddlewareChain"""
    
    def test_execute_applies_middleware(self):
        """Тест что execute применяет middleware"""
        middleware1 = Mock(spec=NodeMiddleware)
        middleware1.before_execution.return_value = {"case_id": "test", "step1": True}
        middleware1.after_execution.return_value = {"case_id": "test", "step1": True, "completed": True}
        
        middleware2 = Mock(spec=NodeMiddleware)
        middleware2.before_execution.return_value = {"case_id": "test", "step1": True, "step2": True}
        middleware2.after_execution.return_value = {"case_id": "test", "step1": True, "step2": True, "completed": True}
        
        chain = MiddlewareChain([middleware1, middleware2])
        
        def node_func(state):
            return {"case_id": "test", "step1": True, "step2": True, "completed": True}
        
        initial_state = {"case_id": "test"}
        result = chain.execute(node_func, initial_state, "test_node")
        
        assert result["completed"] is True
        middleware1.before_execution.assert_called_once()
        middleware1.after_execution.assert_called_once()
        middleware2.before_execution.assert_called_once()
        middleware2.after_execution.assert_called_once()
    
    def test_execute_handles_error(self):
        """Тест обработки ошибок в middleware chain"""
        middleware1 = Mock(spec=NodeMiddleware)
        middleware1.before_execution.return_value = {"case_id": "test"}
        middleware1.on_error.return_value = {"case_id": "test", "recovered": True}
        
        chain = MiddlewareChain([middleware1])
        
        def node_func(state):
            raise Exception("Test error")
        
        initial_state = {"case_id": "test"}
        result = chain.execute(node_func, initial_state, "test_node")
        
        assert result["recovered"] is True
        middleware1.on_error.assert_called_once()
    
    def test_add_middleware(self):
        """Тест добавления middleware в цепочку"""
        chain = MiddlewareChain()
        middleware = Mock(spec=NodeMiddleware)
        
        chain.add(middleware)
        
        assert len(chain.middlewares) == 1
        assert chain.middlewares[0] == middleware

