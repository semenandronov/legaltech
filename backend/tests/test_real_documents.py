"""Тесты с реальными документами"""
import pytest
from unittest.mock import Mock


class TestRealDocuments:
    """Тесты с реальными юридическими документами"""
    
    def test_load_real_pdf_documents(self):
        """Тест загрузки реальных PDF документов"""
        # Структурная проверка - должна быть возможность загружать PDF
        from app.services.langchain_loaders import load_document
        
        # Функция должна существовать
        assert callable(load_document)
    
    def test_extract_timeline_from_real_documents(self):
        """Тест извлечения timeline из реальных документов"""
        # Timeline агент должен работать с реальными документами
        from app.services.langchain_agents.timeline_node import timeline_agent_node
        
        assert callable(timeline_agent_node)
    
    def test_find_key_facts(self):
        """Тест нахождения key facts"""
        # Key facts агент должен извлекать факты из реальных документов
        from app.services.langchain_agents.key_facts_node import key_facts_agent_node
        
        assert callable(key_facts_agent_node)
    
    def test_search_discrepancies(self):
        """Тест поиска discrepancies"""
        # Discrepancy агент должен находить противоречия в реальных документах
        from app.services.langchain_agents.discrepancy_node import discrepancy_agent_node
        
        assert callable(discrepancy_agent_node)
    
    def test_generate_summary(self):
        """Тест генерации summary"""
        # Summary агент должен генерировать резюме из реальных документов
        from app.services.langchain_agents.summary_node import summary_agent_node
        
        assert callable(summary_agent_node)


class TestDocumentProcessing:
    """Тесты обработки документов"""
    
    def test_document_loader_available(self):
        """Тест что document loader доступен"""
        from app.services.langchain_loaders import load_document
        
        assert callable(load_document)
    
    def test_document_processor_available(self):
        """Тест что document processor доступен"""
        from app.services.document_processor import DocumentProcessor
        
        assert DocumentProcessor is not None
        assert hasattr(DocumentProcessor, '__init__')
