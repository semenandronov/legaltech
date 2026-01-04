"""Unit tests for runtime middleware"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from app.services.langchain_agents.runtime_middleware import create_runtime_middleware
from app.services.langchain_agents.context_schema import CaseContext
from app.services.langchain_agents.store import CaseStore
from app.services.langchain_agents.tool_runtime import ToolRuntime


class TestRuntimeMiddleware:
    """Тесты для runtime middleware"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        return Mock()
    
    @pytest.fixture
    def mock_rag_service(self):
        """Mock RAG service"""
        return Mock()
    
    @pytest.fixture
    def runtime_middleware(self, mock_db, mock_rag_service):
        """Создать runtime middleware"""
        return create_runtime_middleware(mock_db, mock_rag_service)
    
    def test_middleware_injects_runtime(self, runtime_middleware, mock_db, mock_rag_service):
        """Тест что middleware инжектирует ToolRuntime"""
        def test_tool(case_id: str, **kwargs):
            assert "runtime" in kwargs
            assert isinstance(kwargs["runtime"], ToolRuntime)
            assert kwargs["runtime"].case_id == case_id
            return "success"
        
        wrapped_tool = runtime_middleware(test_tool)
        
        # Создаём mock state для извлечения case_id
        state = {"case_id": "test-case-123"}
        
        # Вызываем wrapped tool с state в kwargs
        result = wrapped_tool(case_id="test-case-123", state=state)
        
        assert result == "success"
    
    def test_middleware_handles_missing_case_id(self, runtime_middleware):
        """Тест обработки отсутствующего case_id"""
        def test_tool(**kwargs):
            return "success"
        
        wrapped_tool = runtime_middleware(test_tool)
        
        # Вызываем без case_id
        # Должен fallback на вызов без runtime
        result = wrapped_tool(some_arg="value")
        
        assert result == "success"
    
    def test_middleware_creates_case_store(self, runtime_middleware, mock_db, mock_rag_service):
        """Тест что middleware создаёт CaseStore"""
        def test_tool(case_id: str, **kwargs):
            runtime = kwargs.get("runtime")
            assert runtime is not None
            assert runtime.store is not None
            assert isinstance(runtime.store, CaseStore)
            return "success"
        
        wrapped_tool = runtime_middleware(test_tool)
        state = {"case_id": "test-case"}
        
        result = wrapped_tool(case_id="test-case", state=state)
        
        assert result == "success"
    
    def test_middleware_creates_case_context(self, runtime_middleware, mock_db, mock_rag_service):
        """Тест что middleware создаёт CaseContext"""
        def test_tool(case_id: str, **kwargs):
            runtime = kwargs.get("runtime")
            assert runtime is not None
            assert runtime.context is not None
            assert isinstance(runtime.context, CaseContext)
            assert runtime.context.case_id == case_id
            return "success"
        
        wrapped_tool = runtime_middleware(test_tool)
        state = {"case_id": "test-case"}
        
        result = wrapped_tool(case_id="test-case", state=state)
        
        assert result == "success"
    
    def test_middleware_fallback_on_error(self, runtime_middleware):
        """Тест fallback при ошибке создания runtime"""
        def test_tool(case_id: str, **kwargs):
            # Tool работает даже без runtime
            return "success"
        
        wrapped_tool = runtime_middleware(test_tool)
        
        # Вызываем с некорректными данными
        # Middleware должен обработать ошибку и вызвать tool без runtime
        result = wrapped_tool(case_id="test-case")
        
        assert result == "success"

