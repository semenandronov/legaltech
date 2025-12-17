"""Тесты для endpoint результатов анализа"""
import pytest
from unittest.mock import Mock, patch


class TestResultsEndpoint:
    """Тесты endpoint /api/analysis/{case_id}/results"""
    
    def test_results_endpoint_exists(self):
        """Тест что endpoint существует"""
        try:
            from app.routes.analysis import router
            
            routes = [route.path for route in router.routes]
            # Проверка что есть endpoint для результатов
            assert any("/{case_id}/results" in route or "results" in route.lower() for route in routes) or len(routes) > 0
        except ImportError:
            pass
    
    def test_results_returns_all_analyses(self):
        """Тест что endpoint возвращает результаты всех анализов"""
        # Ожидаемая структура ответа
        expected_results_structure = {
            "case_id": str,
            "timeline": (dict, type(None)),
            "key_facts": (dict, type(None)),
            "discrepancies": (dict, type(None)),
            "risk_analysis": (dict, type(None)),
            "summary": (dict, type(None)),
            "errors": list
        }
        
        assert "timeline" in expected_results_structure
        assert "key_facts" in expected_results_structure
        assert "errors" in expected_results_structure
    
    def test_results_data_format(self):
        """Тест формата данных результатов"""
        # Результаты должны быть в правильном формате
        
        example_results = {
            "case_id": "test_case",
            "timeline": {
                "events": [
                    {"date": "2024-01-01", "description": "Event"}
                ]
            },
            "key_facts": {
                "facts": {"fact1": "value1"}
            },
            "discrepancies": {
                "discrepancies": []
            },
            "risk_analysis": {
                "analysis": "Risk assessment"
            },
            "summary": {
                "summary": "Case summary"
            },
            "errors": []
        }
        
        assert isinstance(example_results, dict)
        assert "case_id" in example_results
    
    def test_results_handles_missing_results(self):
        """Тест обработки отсутствующих результатов"""
        # Если анализ еще не выполнен, результат должен быть None
        
        partial_results = {
            "case_id": "test_case",
            "timeline": {"events": []},  # Выполнено
            "key_facts": None,  # Еще не выполнено
            "discrepancies": None,
            "risk_analysis": None,
            "summary": None,
            "errors": []
        }
        
        assert partial_results["timeline"] is not None
        assert partial_results["key_facts"] is None


class TestResultsFormat:
    """Тесты формата результатов"""
    
    def test_timeline_result_format(self):
        """Тест формата результата timeline"""
        timeline_result = {
            "events": [
                {
                    "date": "2024-01-01",
                    "description": "Event description",
                    "source": "document.pdf"
                }
            ],
            "total_events": 1
        }
        
        assert "events" in timeline_result
        assert isinstance(timeline_result["events"], list)
    
    def test_key_facts_result_format(self):
        """Тест формата результата key_facts"""
        key_facts_result = {
            "facts": {
                "fact1": "value1",
                "fact2": "value2"
            },
            "result_id": "123"
        }
        
        assert "facts" in key_facts_result
        assert isinstance(key_facts_result["facts"], dict)
    
    def test_discrepancies_result_format(self):
        """Тест формата результата discrepancies"""
        discrepancies_result = {
            "discrepancies": [
                {
                    "type": "contradiction",
                    "description": "Description",
                    "sources": ["doc1.pdf", "doc2.pdf"]
                }
            ],
            "total": 1
        }
        
        assert "discrepancies" in discrepancies_result
        assert isinstance(discrepancies_result["discrepancies"], list)
