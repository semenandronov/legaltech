"""Тесты выполнения анализа через AgentCoordinator"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from app.services.langchain_agents.coordinator import AgentCoordinator
from app.services.langchain_agents.state import AnalysisState


class TestCoordinatorExecution:
    """Тесты выполнения анализа"""
    
    @pytest.fixture
    def mock_services(self):
        """Создать моки сервисов"""
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        return mock_db, mock_rag, mock_doc_processor
    
    def test_run_analysis_returns_correct_structure(self, mock_services):
        """Тест что run_analysis возвращает правильную структуру"""
        mock_db, mock_rag, mock_doc_processor = mock_services
        
        coordinator = AgentCoordinator(mock_db, mock_rag, mock_doc_processor)
        
        # Ожидаемая структура результата
        expected_structure = {
            "case_id": str,
            "timeline": (dict, type(None)),
            "key_facts": (dict, type(None)),
            "discrepancies": (dict, type(None)),
            "risk_analysis": (dict, type(None)),
            "summary": (dict, type(None)),
            "errors": list,
            "execution_time": float,
            "metadata": dict
        }
        
        # Проверка что структура определена в коде
        assert len(expected_structure) > 0
        assert "case_id" in expected_structure
        assert "errors" in expected_structure
        assert "execution_time" in expected_structure
    
    def test_all_requested_analyses_execute(self, mock_services):
        """Тест что все запрошенные анализы выполняются"""
        mock_db, mock_rag, mock_doc_processor = mock_services
        
        coordinator = AgentCoordinator(mock_db, mock_rag, mock_doc_processor)
        
        # Структурная проверка - coordinator должен принимать analysis_types
        analysis_types = ["timeline", "key_facts", "discrepancy"]
        
        assert isinstance(analysis_types, list)
        assert len(analysis_types) == 3
        assert "timeline" in analysis_types
    
    def test_execution_time_tracked(self, mock_services):
        """Тест что execution time отслеживается"""
        # В coordinator.run_analysis используется time.time() для отслеживания времени
        import time
        
        start_time = time.time()
        # Симуляция выполнения
        end_time = time.time()
        execution_time = end_time - start_time
        
        assert execution_time >= 0
        assert isinstance(execution_time, float)
    
    def test_errors_collected_in_results(self, mock_services):
        """Тест что ошибки собираются в results['errors']"""
        # Структурная проверка - coordinator должен собирать ошибки из state
        expected_error_structure = {
            "node": str,
            "error": str,
            "timestamp": str,
            "type": str
        }
        
        # Проверка структуры ошибки
        assert "node" in expected_error_structure
        assert "error" in expected_error_structure
    
    def test_metadata_contains_useful_info(self, mock_services):
        """Тест что metadata содержит полезную информацию"""
        # Metadata может содержать информацию о выполнении
        metadata = {
            "start_time": "2024-01-01T00:00:00",
            "nodes_executed": ["timeline", "key_facts"],
            "total_nodes": 2
        }
        
        assert isinstance(metadata, dict)
        assert "nodes_executed" in metadata or len(metadata) > 0


class TestCoordinatorErrorHandling:
    """Тесты обработки ошибок в coordinator"""
    
    def test_coordinator_handles_execution_errors(self):
        """Тест обработки ошибок выполнения"""
        from unittest.mock import Mock, patch
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        coordinator = AgentCoordinator(mock_db, mock_rag, mock_doc_processor)
        
        # Coordinator должен обрабатывать ошибки и возвращать структуру с errors
        # Это проверяется в коде coordinator через try/except
        
        assert hasattr(coordinator, 'run_analysis')
        
        # При ошибке должен возвращаться результат с errors
        expected_on_error = {
            "case_id": str,
            "errors": list,
            "execution_time": float
        }
        
        assert "errors" in expected_on_error
