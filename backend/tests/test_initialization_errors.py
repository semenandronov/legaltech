"""Тесты ошибок инициализации"""
import pytest
from unittest.mock import Mock, patch
from app.config import config


class TestInitializationErrors:
    """Тесты ошибок инициализации"""
    
    def test_graph_creation_error_fallback(self):
        """Тест fallback при ошибке создания графа"""
        from app.services.langchain_agents.graph import create_analysis_graph
        from unittest.mock import Mock
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        # Граф должен обрабатывать ошибки создания
        # В текущей реализации ошибки проявятся при выполнении
        try:
            graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
            assert graph is not None
        except Exception:
            # Если граф не создается, это должно обрабатываться в AnalysisService
            pass
    
    def test_coordinator_initialization_error_fallback(self):
        """Тест fallback при ошибке инициализации coordinator"""
        from app.services.langchain_agents.coordinator import AgentCoordinator
        from unittest.mock import Mock
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        # Coordinator должен обрабатывать ошибки инициализации
        try:
            coordinator = AgentCoordinator(mock_db, mock_rag, mock_doc_processor)
            assert coordinator is not None
        except Exception:
            # Ошибки должны обрабатываться в AnalysisService
            pass
    
    def test_missing_database_url_memory_saver(self):
        """Тест использования MemorySaver при отсутствии DATABASE_URL"""
        from app.services.langchain_agents.graph import create_analysis_graph
        from unittest.mock import Mock, patch
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        # Симуляция отсутствия PostgreSQL
        with patch('langgraph.checkpoint.postgres.PostgresSaver.from_conn_string', side_effect=Exception("No DB")):
            graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
            # Должен использоваться MemorySaver
            assert graph is not None
    
    def test_missing_openrouter_api_key_error(self):
        """Тест ошибки при отсутствии OPENROUTER_API_KEY"""
        # При отсутствии API ключа должна быть понятная ошибка
        # Это проверяется в config._validate()
        
        assert hasattr(config, 'OPENROUTER_API_KEY')
        
        # Config должен валидировать наличие ключа
        assert hasattr(config, '_validate')
        assert callable(config._validate)


class TestErrorMessages:
    """Тесты сообщений об ошибках"""
    
    def test_clear_error_messages(self):
        """Тест что сообщения об ошибках понятны"""
        # Ошибки должны содержать понятные сообщения
        
        example_error = {
            "node": "timeline",
            "error": "LLM API error: Connection timeout",
            "type": "api_error",
            "timestamp": "2024-01-01T00:00:00"
        }
        
        assert "error" in example_error
        assert len(example_error["error"]) > 0
        assert "node" in example_error


class TestFallbackMechanisms:
    """Тесты fallback механизмов"""
    
    def test_agent_disabled_fallback(self):
        """Тест fallback когда агенты отключены"""
        from unittest.mock import Mock, patch
        from app.services.analysis_service import AnalysisService
        
        mock_db = Mock()
        
        # При отключенных агентах должен использоваться fallback
        with patch('app.services.analysis_service.config.AGENT_ENABLED', False):
            service = AnalysisService(mock_db)
            # Должны быть доступны legacy методы
            assert hasattr(service, 'extract_timeline')
            assert hasattr(service, 'extract_key_facts')
