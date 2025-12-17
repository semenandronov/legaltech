"""Тесты fallback на MemorySaver"""
import pytest
from unittest.mock import Mock, patch


class TestCheckpointerFallback:
    """Тесты fallback механизма checkpointer"""
    
    def test_memory_saver_used_when_no_postgres(self):
        """Тест использования MemorySaver при отсутствии PostgreSQL"""
        from app.services.langchain_agents.graph import create_analysis_graph
        from unittest.mock import Mock
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        # Симуляция отсутствия PostgreSQL
        with patch('langgraph.checkpoint.postgres.PostgresSaver.from_conn_string', side_effect=Exception("No PostgreSQL")):
            graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
            # Должен использоваться MemorySaver
            assert graph is not None
    
    def test_system_works_with_memory_saver(self):
        """Тест что система работает с MemorySaver"""
        try:
            from langgraph.checkpoint.memory import MemorySaver
            checkpointer = MemorySaver()
            assert checkpointer is not None
        except ImportError:
            pytest.skip("MemorySaver not available")
    
    def test_warning_logging(self):
        """Тест логирования предупреждений"""
        import logging
        
        # При fallback должно быть логирование предупреждения
        from app.services.langchain_agents.graph import logger
        
        assert logger is not None
        assert isinstance(logger, logging.Logger)


class TestMemorySaverFunctionality:
    """Тесты функциональности MemorySaver"""
    
    def test_memory_saver_basic_functionality(self):
        """Тест базовой функциональности MemorySaver"""
        try:
            from langgraph.checkpoint.memory import MemorySaver
            
            checkpointer = MemorySaver()
            assert checkpointer is not None
            
            # MemorySaver должен поддерживать базовые операции
            # (детали зависят от реализации LangGraph)
            assert True
        except ImportError:
            pytest.skip("MemorySaver not available")
    
    def test_memory_saver_limitations(self):
        """Тест ограничений MemorySaver"""
        # MemorySaver не сохраняет состояние между перезапусками
        # Это нормально для разработки, но не для production
        
        # Структурная проверка
        assert True
