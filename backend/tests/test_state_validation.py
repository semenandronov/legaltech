"""Тесты для валидации AnalysisState"""
import pytest
from typing import Dict, Any
from app.services.langchain_agents.state import AnalysisState


class TestAnalysisState:
    """Тесты для структуры и валидации AnalysisState"""
    
    def test_state_is_typed_dict(self):
        """Проверка, что AnalysisState является TypedDict"""
        assert hasattr(AnalysisState, "__annotations__")
        assert isinstance(AnalysisState.__annotations__, dict)
    
    def test_state_has_required_fields(self):
        """Проверка наличия всех обязательных полей"""
        required_fields = {
            "case_id": str,
            "messages": list,
            "analysis_types": list,
            "errors": list,
            "metadata": dict,
        }
        
        annotations = AnalysisState.__annotations__
        
        for field_name, field_type in required_fields.items():
            assert field_name in annotations, f"Поле {field_name} отсутствует в AnalysisState"
    
    def test_state_has_optional_result_fields(self):
        """Проверка наличия опциональных полей результатов"""
        optional_fields = [
            "timeline_result",
            "key_facts_result",
            "discrepancy_result",
            "risk_result",
            "summary_result",
        ]
        
        annotations = AnalysisState.__annotations__
        
        for field_name in optional_fields:
            assert field_name in annotations, f"Поле {field_name} отсутствует в AnalysisState"
            # Проверка, что поле опциональное (Optional[...])
            field_type = annotations[field_name]
            type_str = str(field_type)
            assert "Optional" in type_str or "None" in type_str, \
                f"Поле {field_name} должно быть опциональным"
    
    def test_state_field_types(self):
        """Проверка типов полей"""
        annotations = AnalysisState.__annotations__
        
        # Проверка типов основных полей
        assert annotations["case_id"] == str
        assert annotations["analysis_types"] == list
        assert annotations["errors"] == list
        assert annotations["metadata"] == dict
    
    def test_create_valid_state(self):
        """Проверка создания валидного состояния"""
        from langchain_core.messages import HumanMessage
        
        state: AnalysisState = {
            "case_id": "test-case-123",
            "messages": [HumanMessage(content="test")],
            "analysis_types": ["timeline", "key_facts"],
            "errors": [],
            "metadata": {},
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
        }
        
        assert state["case_id"] == "test-case-123"
        assert len(state["messages"]) == 1
        assert len(state["analysis_types"]) == 2
        assert state["timeline_result"] is None
    
    def test_state_with_results(self):
        """Проверка состояния с результатами"""
        from langchain_core.messages import HumanMessage
        
        state: AnalysisState = {
            "case_id": "test-case-123",
            "messages": [HumanMessage(content="test")],
            "analysis_types": ["timeline"],
            "errors": [],
            "metadata": {},
            "timeline_result": {"events": [{"date": "2024-01-01", "description": "Event"}]},
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
        }
        
        assert state["timeline_result"] is not None
        assert "events" in state["timeline_result"]
    
    def test_state_with_errors(self):
        """Проверка состояния с ошибками"""
        from langchain_core.messages import HumanMessage
        
        state: AnalysisState = {
            "case_id": "test-case-123",
            "messages": [HumanMessage(content="test")],
            "analysis_types": ["timeline"],
            "errors": [
                {"node": "timeline", "error": "Test error", "timestamp": "2024-01-01T00:00:00"}
            ],
            "metadata": {},
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
        }
        
        assert len(state["errors"]) == 1
        assert state["errors"][0]["node"] == "timeline"
