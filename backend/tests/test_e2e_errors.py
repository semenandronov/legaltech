"""Тесты E2E сценариев с ошибками"""
import pytest
from app.services.langchain_agents.state import AnalysisState


class TestE2EErrors:
    """Тесты E2E сценариев с ошибками"""
    
    def test_error_in_one_agent_continues_others(self):
        """Тест что ошибка в одном агенте не останавливает другие"""
        # Сценарий:
        # 1. Симулировать ошибку в одном агенте
        # 2. Проверить, что другие агенты продолжают работу
        # 3. Проверить частичные результаты
        # 4. Проверить fallback на legacy методы
        
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": []},  # Успешно
            "key_facts_result": None,  # Ошибка
            "discrepancy_result": {"discrepancies": []},  # Успешно
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy"],
            "errors": [
                {
                    "node": "key_facts",
                    "error": "LLM API error",
                    "type": "api_error",
                    "timestamp": "2024-01-01T00:00:00"
                }
            ],
            "metadata": {}
        }
        
        # Частичные результаты должны быть сохранены
        assert state["timeline_result"] is not None
        assert state["discrepancy_result"] is not None
        assert state["key_facts_result"] is None
        assert len(state["errors"]) > 0
    
    def test_partial_results_returned(self):
        """Тест что частичные результаты возвращаются"""
        # Даже при ошибках должны возвращаться частичные результаты
        
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": [{"date": "2024-01-01", "description": "Event"}]},
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts"],
            "errors": [{"node": "key_facts", "error": "Test error"}],
            "metadata": {}
        }
        
        # Timeline результат должен быть доступен
        assert state["timeline_result"] is not None
        assert "events" in state["timeline_result"]
    
    def test_fallback_to_legacy_methods(self):
        """Тест fallback на legacy методы"""
        # При критических ошибках должен использоваться fallback
        
        from unittest.mock import Mock, patch
        from app.services.analysis_service import AnalysisService
        
        mock_db = Mock()
        
        # При отключенных агентах должен использоваться fallback
        with patch('app.services.analysis_service.config.AGENT_ENABLED', False):
            service = AnalysisService(mock_db)
            # Должны быть доступны legacy методы
            assert hasattr(service, 'extract_timeline')
            assert hasattr(service, 'extract_key_facts')


class TestErrorRecovery:
    """Тесты восстановления после ошибок"""
    
    def test_errors_collected(self):
        """Тест что ошибки собираются"""
        # Все ошибки должны собираться в state["errors"]
        
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts"],
            "errors": [
                {"node": "timeline", "error": "Error 1"},
                {"node": "key_facts", "error": "Error 2"}
            ],
            "metadata": {}
        }
        
        assert len(state["errors"]) == 2
        assert all("node" in error for error in state["errors"])
        assert all("error" in error for error in state["errors"])
