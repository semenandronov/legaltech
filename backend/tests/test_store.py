"""Unit tests for CaseStore"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from app.services.langchain_agents.store import CaseStore
from app.services.rag_service import RAGService
from langchain_core.documents import Document


class TestCaseStore:
    """Тесты для CaseStore"""
    
    @pytest.fixture
    def mock_db(self):
        """Mock database session"""
        return Mock()
    
    @pytest.fixture
    def mock_rag_service(self):
        """Mock RAG service"""
        rag_service = Mock(spec=RAGService)
        return rag_service
    
    @pytest.fixture
    def case_store(self, mock_db, mock_rag_service):
        """Создать CaseStore instance"""
        return CaseStore(db=mock_db, case_id="test-case", rag_service=mock_rag_service)
    
    def test_search_delegates_to_rag_service(self, case_store, mock_rag_service):
        """Тест что search делегирует в RAG service"""
        mock_documents = [
            Document(page_content="Test content", metadata={"source": "doc1.pdf"})
        ]
        mock_rag_service.retrieve_context.return_value = mock_documents
        
        result = case_store.search(query="test query", k=10)
        
        assert len(result) == 1
        assert result[0].page_content == "Test content"
        mock_rag_service.retrieve_context.assert_called_once()
    
    def test_search_with_filters(self, case_store, mock_rag_service):
        """Тест search с фильтрами"""
        mock_documents = []
        mock_rag_service.retrieve_context.return_value = mock_documents
        
        filters = {"doc_types": ["contract", "statement"]}
        case_store.search(query="test", filters=filters, k=5)
        
        call_args = mock_rag_service.retrieve_context.call_args
        assert call_args.kwargs.get("doc_types") == ["contract", "statement"]
    
    def test_get_entities(self, case_store, mock_db):
        """Тест получения сущностей"""
        from app.models.analysis import ExtractedEntity
        
        # Mock entities
        entity1 = Mock(spec=ExtractedEntity)
        entity1.__dict__ = {"id": "1", "name": "Test Entity", "type": "person"}
        entity2 = Mock(spec=ExtractedEntity)
        entity2.__dict__ = {"id": "2", "name": "Test Org", "type": "organization"}
        
        mock_query = Mock()
        mock_query.filter.return_value.all.return_value = [entity1, entity2]
        mock_db.query.return_value = mock_query
        
        result = case_store.get_entities()
        
        assert len(result) == 2
        assert result[0]["name"] == "Test Entity"
        assert result[1]["name"] == "Test Org"
    
    def test_save_analysis_event(self, case_store):
        """Тест сохранения события анализа"""
        # Метод пока только логирует, проверяем что не падает
        case_store.save_analysis_event(
            event_type="test_event",
            data={"key": "value"}
        )
        # Если не упало - тест пройден
    
    def test_get_previous_results(self, case_store, mock_db):
        """Тест получения предыдущих результатов"""
        from app.models.analysis import AnalysisResult
        
        # Mock previous result
        result = Mock(spec=AnalysisResult)
        result.result_data = {"analysis": "previous"}
        
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = result
        mock_db.query.return_value = mock_query
        
        previous = case_store.get_previous_results("timeline")
        
        assert previous == {"analysis": "previous"}
    
    def test_get_previous_results_not_found(self, case_store, mock_db):
        """Тест когда предыдущих результатов нет"""
        mock_query = Mock()
        mock_query.filter.return_value.order_by.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        
        previous = case_store.get_previous_results("timeline")
        
        assert previous is None
    
    def test_get_case_info(self, case_store, mock_db):
        """Тест получения информации о деле"""
        from app.models.case import Case
        
        case = Mock(spec=Case)
        case.id = "test-case"
        case.title = "Test Case"
        case.description = "Test Description"
        case.case_type = "litigation"
        case.num_documents = 10
        case.created_at = Mock()
        case.created_at.isoformat.return_value = "2024-01-01T00:00:00"
        case.case_metadata = {"key": "value"}
        
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = case
        mock_db.query.return_value = mock_query
        
        info = case_store.get_case_info()
        
        assert info["case_id"] == "test-case"
        assert info["title"] == "Test Case"
        assert info["case_type"] == "litigation"
        assert info["num_documents"] == 10
    
    def test_get_case_info_not_found(self, case_store, mock_db):
        """Тест когда дело не найдено"""
        mock_query = Mock()
        mock_query.filter.return_value.first.return_value = None
        mock_db.query.return_value = mock_query
        
        info = case_store.get_case_info()
        
        assert info == {"case_id": "test-case"}

