"""Unit tests for CaseContext schema"""
import pytest
from datetime import datetime
from app.services.langchain_agents.context_schema import CaseContext
from app.models.case import Case


class TestCaseContext:
    """Тесты для CaseContext"""
    
    def test_create_minimal_context(self):
        """Тест создания минимального контекста"""
        context = CaseContext.from_minimal(case_id="test-case-123", user_id="user-456")
        
        assert context.case_id == "test-case-123"
        assert context.user_id == "user-456"
        assert context.jurisdiction is None
        assert context.case_type is None
        assert context.client_name is None
        assert isinstance(context.created_at, datetime)
    
    def test_context_is_frozen(self):
        """Тест что контекст неизменяемый (frozen)"""
        context = CaseContext.from_minimal(case_id="test-case", user_id="user")
        
        # Попытка изменить поле должна вызвать ошибку
        with pytest.raises(Exception):  # Pydantic ValidationError или TypeError
            context.case_id = "new-case-id"
    
    def test_from_case_model(self):
        """Тест создания контекста из модели Case"""
        # Создаём mock Case объект
        case = Case(
            id="case-123",
            user_id="user-456",
            case_type="litigation",
            case_metadata={
                "jurisdiction": "РФ",
                "client_name": "ООО Тест"
            },
            created_at=datetime.utcnow()
        )
        
        context = CaseContext.from_case_model(case)
        
        assert context.case_id == "case-123"
        assert context.user_id == "user-456"
        assert context.case_type == "litigation"
        assert context.jurisdiction == "РФ"
        assert context.client_name == "ООО Тест"
    
    def test_from_case_model_without_metadata(self):
        """Тест создания контекста из Case без metadata"""
        case = Case(
            id="case-123",
            user_id="user-456",
            case_type="litigation",
            case_metadata=None,
            created_at=datetime.utcnow()
        )
        
        context = CaseContext.from_case_model(case)
        
        assert context.case_id == "case-123"
        assert context.user_id == "user-456"
        assert context.case_type == "litigation"
        assert context.jurisdiction is None
        assert context.client_name is None
    
    def test_context_serialization(self):
        """Тест сериализации контекста в JSON"""
        context = CaseContext.from_minimal(case_id="test-case", user_id="user")
        
        # Проверяем что можно сериализовать
        context_dict = context.dict()
        assert isinstance(context_dict, dict)
        assert context_dict["case_id"] == "test-case"
        assert context_dict["user_id"] == "user"
        
        # Проверяем JSON сериализацию
        import json
        json_str = context.json()
        assert isinstance(json_str, str)
        assert "test-case" in json_str

