"""Unit tests for ToolRuntime"""
import pytest
from app.services.langchain_agents.tool_runtime import ToolRuntime
from app.services.langchain_agents.context_schema import CaseContext
from app.services.langchain_agents.store import CaseStore
from app.services.langchain_agents.state import AnalysisState
from unittest.mock import Mock, MagicMock


class TestToolRuntime:
    """Тесты для ToolRuntime"""
    
    def test_create_runtime(self):
        """Тест создания ToolRuntime"""
        context = CaseContext.from_minimal(case_id="test-case", user_id="user")
        store = Mock(spec=CaseStore)
        
        runtime = ToolRuntime(context=context, store=store)
        
        assert runtime.context == context
        assert runtime.store == store
        assert runtime.case_id == "test-case"
        assert runtime.user_id == "user"
    
    def test_get_state_field(self):
        """Тест получения поля из state"""
        context = CaseContext.from_minimal(case_id="test-case", user_id="user")
        store = Mock(spec=CaseStore)
        
        state = {
            "case_id": "test-case",
            "messages": [],
            "analysis_types": ["timeline"]
        }
        
        runtime = ToolRuntime(context=context, store=store, state=state)
        
        assert runtime.get_state_field("case_id") == "test-case"
        assert runtime.get_state_field("analysis_types") == ["timeline"]
        assert runtime.get_state_field("nonexistent", "default") == "default"
    
    def test_get_state_field_without_state(self):
        """Тест получения поля когда state не передан"""
        context = CaseContext.from_minimal(case_id="test-case", user_id="user")
        store = Mock(spec=CaseStore)
        
        runtime = ToolRuntime(context=context, store=store)
        
        assert runtime.get_state_field("case_id", "default") == "default"
    
    def test_case_id_property(self):
        """Тест свойства case_id"""
        context = CaseContext.from_minimal(case_id="test-case-123", user_id="user")
        store = Mock(spec=CaseStore)
        
        runtime = ToolRuntime(context=context, store=store)
        
        assert runtime.case_id == "test-case-123"
    
    def test_user_id_property(self):
        """Тест свойства user_id"""
        context = CaseContext.from_minimal(case_id="test-case", user_id="user-456")
        store = Mock(spec=CaseStore)
        
        runtime = ToolRuntime(context=context, store=store)
        
        assert runtime.user_id == "user-456"

