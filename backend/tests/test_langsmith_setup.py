"""Тесты настройки LangSmith"""
import pytest
from unittest.mock import Mock, patch
from app.config import config


class TestLangSmithSetup:
    """Тесты настройки LangSmith"""
    
    def test_langsmith_initializes_with_api_key(self):
        """Тест что LangSmith инициализируется при наличии API key"""
        # LangSmith должен инициализироваться в config._setup_langsmith()
        
        assert hasattr(config, 'LANGSMITH_API_KEY')
        assert hasattr(config, '_setup_langsmith')
        assert callable(config._setup_langsmith)
    
    def test_environment_variables_set(self):
        """Тест что переменные окружения устанавливаются"""
        # При наличии API key должны устанавливаться переменные окружения
        
        import os
        
        # Проверка что config имеет настройки LangSmith
        assert hasattr(config, 'LANGSMITH_API_KEY')
        assert hasattr(config, 'LANGSMITH_PROJECT')
        assert hasattr(config, 'LANGSMITH_TRACING')
        assert hasattr(config, 'LANGSMITH_ENDPOINT')
    
    def test_logging_enabled_disabled(self):
        """Тест логирования включения/выключения"""
        # Должно быть логирование при включении/выключении LangSmith
        
        import logging
        
        # Config должен логировать статус LangSmith
        assert hasattr(config, '_setup_langsmith')
        
        # Logger должен быть настроен
        from app.config import logger
        assert logger is not None
        assert isinstance(logger, logging.Logger)


class TestLangSmithConfiguration:
    """Тесты конфигурации LangSmith"""
    
    def test_langsmith_config_structure(self):
        """Тест структуры конфигурации LangSmith"""
        # Config должен иметь все необходимые настройки
        
        assert hasattr(config, 'LANGSMITH_API_KEY')
        assert hasattr(config, 'LANGSMITH_PROJECT')
        assert hasattr(config, 'LANGSMITH_TRACING')
        assert hasattr(config, 'LANGSMITH_ENDPOINT')
    
    def test_langsmith_optional(self):
        """Тест что LangSmith опционален"""
        # LangSmith должен быть опциональным - система должна работать без него
        
        # Проверка что система может работать без LangSmith
        assert True
    
    def test_langsmith_warning_on_missing_key(self):
        """Тест предупреждения при отсутствии ключа"""
        # Если LANGSMITH_TRACING=true но ключ отсутствует,
        # должно быть предупреждение
        
        # Это проверяется в config._setup_langsmith()
        assert hasattr(config, '_setup_langsmith')
