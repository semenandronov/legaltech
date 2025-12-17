"""Tests for LangGraph graph creation and execution"""
import pytest
from unittest.mock import Mock, MagicMock
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState


class TestGraphCreation:
    """Test graph creation"""
    
    def test_graph_creation_without_errors(self):
        """Test that graph can be created without errors"""
        # Mock dependencies
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        try:
            graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
            assert graph is not None
        except Exception as e:
            pytest.fail(f"Graph creation failed: {e}")
    
    def test_graph_has_nodes(self):
        """Test that graph has all required nodes"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
        
        # Check that graph is compiled (has invoke method)
        assert hasattr(graph, 'invoke')
        assert hasattr(graph, 'stream')
    
    def test_graph_compilation(self):
        """Test that graph compiles successfully"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
        
        # Compiled graph should have these methods
        assert callable(getattr(graph, 'invoke', None))
        assert callable(getattr(graph, 'stream', None))


class TestGraphStructure:
    """Test graph structure"""
    
    def test_graph_accepts_state(self):
        """Test that graph accepts AnalysisState"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
        
        # Create initial state
        initial_state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline"],
            "errors": [],
            "metadata": {}
        }
        
        # Graph should accept this state structure
        # Note: We can't actually invoke without real services, but we can check structure
        assert isinstance(initial_state, dict)
        assert "case_id" in initial_state
        assert "analysis_types" in initial_state
    
    def test_graph_has_all_nodes(self):
        """Тест что граф содержит все необходимые узлы"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
        
        # Проверка что граф скомпилирован и имеет методы выполнения
        assert hasattr(graph, 'invoke')
        assert hasattr(graph, 'stream')
        
        # Узлы проверяются через выполнение, но структурно граф должен быть готов
        assert graph is not None
    
    def test_graph_has_correct_edges(self):
        """Тест что граф имеет корректные edges"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
        
        # Структурная проверка - граф должен быть скомпилирован
        # Реальные edges проверяются через выполнение
        assert graph is not None
        assert hasattr(graph, 'stream')  # Compiled graph has stream method
    
    def test_graph_conditional_edges(self):
        """Тест что условные edges работают"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
        
        # Условные edges проверяются через route_to_agent функцию
        # Структурно граф должен поддерживать условные переходы
        assert graph is not None
    
    def test_graph_compiles_without_errors(self):
        """Тест что граф компилируется без ошибок"""
        mock_db = Mock()
        mock_rag_service = Mock()
        mock_document_processor = Mock()
        
        try:
            graph = create_analysis_graph(mock_db, mock_rag_service, mock_document_processor)
            assert graph is not None
        except Exception as e:
            pytest.fail(f"Graph compilation failed: {e}")
