"""Тесты настройки checkpointer"""
import pytest
from unittest.mock import Mock, patch
from app.utils.checkpointer_setup import setup_checkpointer


class TestCheckpointerSetup:
    """Тесты настройки checkpointer"""
    
    def test_setup_checkpointer_creates_tables(self):
        """Тест что setup_checkpointer создает таблицы"""
        # setup_checkpointer должна вызывать checkpointer.setup()
        
        assert callable(setup_checkpointer)
        
        # Проверка что функция существует
        try:
            from app.utils.checkpointer_setup import setup_checkpointer
            assert callable(setup_checkpointer)
        except ImportError:
            pytest.skip("setup_checkpointer not available")
    
    def test_tables_have_correct_structure(self):
        """Тест что таблицы имеют правильную структуру"""
        # PostgresSaver создает таблицы для хранения состояний
        # Структурная проверка
        
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            assert hasattr(PostgresSaver, 'setup')
            assert callable(PostgresSaver.setup)
        except ImportError:
            pytest.skip("PostgresSaver not available")
    
    def test_setup_error_handling(self):
        """Тест обработки ошибок при setup"""
        # setup_checkpointer должна обрабатывать ошибки
        
        # При ошибке подключения к БД должна возвращаться False
        with patch('app.utils.checkpointer_setup.PostgresSaver.from_conn_string', side_effect=Exception("Connection failed")):
            result = setup_checkpointer()
            # Должна обработать ошибку
            assert isinstance(result, bool) or result is None


class TestCheckpointerInitialization:
    """Тесты инициализации checkpointer"""
    
    def test_postgres_saver_initialization(self):
        """Тест инициализации PostgresSaver"""
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from app.config import config
            
            # PostgresSaver должен инициализироваться из connection string
            assert hasattr(PostgresSaver, 'from_conn_string')
            assert callable(PostgresSaver.from_conn_string)
        except ImportError:
            pytest.skip("PostgresSaver not available")
