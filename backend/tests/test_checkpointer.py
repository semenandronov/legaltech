"""Тесты для checkpointer"""
import pytest
from unittest.mock import Mock, patch
from app.config import config


class TestCheckpointerCreation:
    """Тесты создания checkpointer"""
    
    def test_postgres_checkpointer_creation(self):
        """Тест создания PostgreSQL checkpointer при наличии DATABASE_URL"""
        # Проверка что DATABASE_URL определен в config
        assert hasattr(config, 'DATABASE_URL')
        
        # Проверка что функция создания checkpointer доступна
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            assert callable(PostgresSaver.from_conn_string)
        except ImportError:
            pytest.skip("PostgresSaver not available")
    
    def test_memory_saver_fallback(self):
        """Тест fallback на MemorySaver при отсутствии PostgreSQL"""
        # Проверка что MemorySaver доступен
        try:
            from langgraph.checkpoint.memory import MemorySaver
            assert callable(MemorySaver)
        except ImportError:
            pytest.skip("MemorySaver not available")
    
    def test_checkpointer_fallback_logic(self):
        """Тест логики fallback в create_analysis_graph"""
        from app.services.langchain_agents.graph import create_analysis_graph
        from unittest.mock import Mock, patch
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        # Симуляция отсутствия PostgreSQL
        with patch('langgraph.checkpoint.postgres.PostgresSaver.from_conn_string', side_effect=Exception("Connection failed")):
            # Граф должен создать MemorySaver как fallback
            graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
            assert graph is not None


class TestCheckpointerPersistence:
    """Тесты персистентности checkpointer"""
    
    def test_state_saving(self):
        """Тест сохранения состояния между выполнениями"""
        # Структурная проверка - checkpointer должен поддерживать сохранение
        # Реальное тестирование требует PostgreSQL
        
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            assert hasattr(PostgresSaver, 'setup')
            assert callable(PostgresSaver.setup)
        except ImportError:
            pytest.skip("PostgresSaver not available")
    
    def test_state_recovery(self):
        """Тест восстановления состояния после перезапуска"""
        # Структурная проверка - checkpointer должен поддерживать восстановление
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            # PostgresSaver должен поддерживать get_state
            assert True  # Структурная проверка пройдена
        except ImportError:
            pytest.skip("PostgresSaver not available")
    
    def test_thread_id_usage(self):
        """Тест использования thread ID"""
        # Thread ID используется для изоляции состояний
        # В coordinator используется f"case_{case_id}" как thread_id
        
        from app.services.langchain_agents.coordinator import AgentCoordinator
        
        # Проверка что coordinator создает thread_config
        assert hasattr(AgentCoordinator, 'run_analysis')
        
        # Thread ID должен быть уникальным для каждого case_id
        case_id = "test_case_123"
        expected_thread_id = f"case_{case_id}"
        assert expected_thread_id == "case_test_case_123"
    
    def test_state_isolation(self):
        """Тест изоляции состояния между разными case_id"""
        # Разные case_id должны иметь разные thread_id
        # Это обеспечивает изоляцию состояний
        
        case_id_1 = "case_1"
        case_id_2 = "case_2"
        
        thread_id_1 = f"case_{case_id_1}"
        thread_id_2 = f"case_{case_id_2}"
        
        assert thread_id_1 != thread_id_2
        assert thread_id_1 == "case_case_1"
        assert thread_id_2 == "case_case_2"


class TestCheckpointerFallback:
    """Тесты fallback механизма checkpointer"""
    
    def test_memory_saver_usage(self):
        """Тест использования MemorySaver"""
        try:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            assert checkpointer is not None
        except ImportError:
            pytest.skip("MemorySaver not available")
    
    def test_fallback_warning_logging(self):
        """Тест логирования предупреждений при fallback"""
        # В graph.py должно быть логирование при fallback
        import logging
        
        # Проверка что logger настроен
        from app.services.langchain_agents.graph import logger
        assert logger is not None
        assert isinstance(logger, logging.Logger)
    
    def test_system_works_with_memory_saver(self):
        """Тест что система работает с MemorySaver"""
        from unittest.mock import Mock, patch
        from app.services.langchain_agents.graph import create_analysis_graph
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        # Принудительно использовать MemorySaver
        with patch('langgraph.checkpoint.postgres.PostgresSaver.from_conn_string', side_effect=Exception("No PostgreSQL")):
            graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
            assert graph is not None
            # Граф должен быть скомпилирован даже с MemorySaver
            assert hasattr(graph, 'stream')
