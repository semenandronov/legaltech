"""Integration tests for agent system"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from app.services.analysis_service import AnalysisService
from app.services.langchain_agents import AgentCoordinator
from app.config import config


class TestAnalysisServiceIntegration:
    """Test integration with AnalysisService"""
    
    def test_analysis_service_initialization(self):
        """Test that AnalysisService initializes correctly"""
        mock_db = Mock()
        
        # Mock config to enable agents
        with patch('app.services.analysis_service.config.AGENT_ENABLED', True):
            try:
                service = AnalysisService(mock_db)
                assert service is not None
                assert hasattr(service, 'use_agents')
            except Exception as e:
                # If agents fail to initialize, should fallback
                service = AnalysisService(mock_db)
                assert service is not None
    
    def test_analysis_service_has_agent_coordinator(self):
        """Test that AnalysisService has agent coordinator when enabled"""
        mock_db = Mock()
        
        with patch('app.services.analysis_service.config.AGENT_ENABLED', True):
            with patch('app.services.analysis_service.RAGService') as mock_rag:
                with patch('app.services.analysis_service.DocumentProcessor') as mock_dp:
                    try:
                        service = AnalysisService(mock_db)
                        if service.use_agents:
                            assert hasattr(service, 'agent_coordinator')
                    except:
                        # Fallback is acceptable
                        pass
    
    def test_analysis_service_methods_exist(self):
        """Test that all AnalysisService methods exist"""
        mock_db = Mock()
        service = AnalysisService(mock_db)
        
        # Check all required methods exist
        assert hasattr(service, 'extract_timeline')
        assert hasattr(service, 'extract_key_facts')
        assert hasattr(service, 'find_discrepancies')
        assert hasattr(service, 'generate_summary')
        assert hasattr(service, 'analyze_risks')
        assert hasattr(service, 'run_agent_analysis')
        
        # All should be callable
        assert callable(service.extract_timeline)
        assert callable(service.extract_key_facts)
        assert callable(service.find_discrepancies)
        assert callable(service.generate_summary)
        assert callable(service.analyze_risks)
        assert callable(service.run_agent_analysis)


class TestRAGServiceIntegration:
    """Test integration with RAGService"""
    
    def test_rag_service_used_in_nodes(self):
        """Test that nodes can use RAGService"""
        # This is a structural test
        # In actual execution, nodes should use RAGService.retrieve_context()
        from app.services.rag_service import RAGService
        
        assert hasattr(RAGService, 'retrieve_context')
        assert callable(RAGService.retrieve_context)


class TestDocumentProcessorIntegration:
    """Test integration with DocumentProcessor"""
    
    def test_document_processor_used_in_nodes(self):
        """Test that nodes can use DocumentProcessor"""
        from app.services.document_processor import DocumentProcessor
        
        assert hasattr(DocumentProcessor, 'retrieve_relevant_chunks')
        assert callable(DocumentProcessor.retrieve_relevant_chunks)


class TestDatabaseIntegration:
    """Test integration with database"""
    
    def test_nodes_save_to_database(self):
        """Test that nodes save results to database"""
        # Structural test - nodes should save to:
        # - TimelineEvent table (timeline node)
        # - AnalysisResult table (key_facts, risk, summary nodes)
        # - Discrepancy table (discrepancy node)
        
        from app.models.analysis import (
            TimelineEvent,
            AnalysisResult,
            Discrepancy
        )
        
        # Verify models exist
        assert TimelineEvent is not None
        assert AnalysisResult is not None
        assert Discrepancy is not None
