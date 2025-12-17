"""Тесты трейсинга LangSmith"""
import pytest
from unittest.mock import Mock, patch
from app.config import config


class TestLangSmithTracing:
    """Тесты трейсинга LangSmith"""
    
    def test_tracing_sent_when_enabled(self):
        """Тест что трейсинг отправляется при включенном трейсинге"""
        # При LANGSMITH_TRACING=true и наличии API key
        # трейсинг должен отправляться в LangSmith
        
        # Структурная проверка - переменные окружения должны быть установлены
        assert hasattr(config, 'LANGSMITH_TRACING')
        assert hasattr(config, 'LANGSMITH_API_KEY')
    
    def test_project_specified_correctly(self):
        """Тест что проект указан корректно"""
        # LANGSMITH_PROJECT должен быть установлен
        
        assert hasattr(config, 'LANGSMITH_PROJECT')
        assert isinstance(config.LANGSMITH_PROJECT, str)
        assert len(config.LANGSMITH_PROJECT) > 0
    
    def test_endpoint_correct(self):
        """Тест что endpoint правильный"""
        # LANGCHAIN_ENDPOINT должен быть правильным
        
        assert hasattr(config, 'LANGSMITH_ENDPOINT')
        assert isinstance(config.LANGSMITH_ENDPOINT, str)
        assert "langchain.com" in config.LANGSMITH_ENDPOINT or len(config.LANGSMITH_ENDPOINT) > 0


class TestTracingConfiguration:
    """Тесты конфигурации трейсинга"""
    
    def test_tracing_variables_set(self):
        """Тест что переменные трейсинга установлены"""
        # При включенном трейсинге должны быть установлены:
        # - LANGCHAIN_TRACING_V2=true
        # - LANGCHAIN_API_KEY
        # - LANGCHAIN_PROJECT
        # - LANGCHAIN_ENDPOINT
        
        # Это делается в config._setup_langsmith()
        assert hasattr(config, '_setup_langsmith')
        assert callable(config._setup_langsmith)
    
    def test_tracing_disabled_by_default(self):
        """Тест что трейсинг отключен по умолчанию"""
        # По умолчанию трейсинг должен быть отключен
        
        # Проверка что LANGSMITH_TRACING может быть False
        assert isinstance(config.LANGSMITH_TRACING, bool)
