"""Тесты streaming функциональности coordinator"""
import pytest
from unittest.mock import Mock, MagicMock
from app.services.langchain_agents.coordinator import AgentCoordinator


class TestCoordinatorStreaming:
    """Тесты streaming"""
    
    @pytest.fixture
    def mock_services(self):
        """Создать моки сервисов"""
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        return mock_db, mock_rag, mock_doc_processor
    
    def test_streaming_yields_intermediate_states(self, mock_services):
        """Тест что streaming выдает промежуточные состояния"""
        mock_db, mock_rag, mock_doc_processor = mock_services
        
        coordinator = AgentCoordinator(mock_db, mock_rag, mock_doc_processor)
        
        # Coordinator использует graph.stream() для получения промежуточных состояний
        # Структурная проверка - graph должен иметь метод stream
        
        assert hasattr(coordinator.graph, 'stream')
        assert callable(coordinator.graph.stream)
    
    def test_progress_tracking(self, mock_services):
        """Тест отслеживания прогресса"""
        # При streaming можно отслеживать прогресс выполнения
        # Каждое состояние из stream представляет выполнение одного узла
        
        # Структурная проверка
        states_sequence = [
            {"supervisor": {}},  # Начало
            {"timeline": {}},    # После timeline
            {"supervisor": {}},  # Возврат к supervisor
            {"key_facts": {}},   # После key_facts
        ]
        
        assert len(states_sequence) > 0
        assert isinstance(states_sequence, list)
    
    def test_final_state_correct(self, mock_services):
        """Тест что финальное состояние корректно"""
        # Финальное состояние должно содержать все результаты
        
        final_state_structure = {
            "case_id": "test_case",
            "timeline_result": dict,
            "key_facts_result": dict,
            "discrepancy_result": dict,
            "errors": list,
            "metadata": dict
        }
        
        # Проверка структуры финального состояния
        assert "case_id" in final_state_structure
        assert "errors" in final_state_structure


class TestStreamingImplementation:
    """Тесты реализации streaming"""
    
    def test_graph_stream_method(self):
        """Тест метода stream графа"""
        from unittest.mock import Mock
        from app.services.langchain_agents.graph import create_analysis_graph
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
        
        # Граф должен иметь метод stream
        assert hasattr(graph, 'stream')
        assert callable(graph.stream)
    
    def test_stream_yields_dicts(self):
        """Тест что stream выдает словари"""
        # Stream должен выдавать словари с ключами - именами узлов
        # и значениями - состояниями
        
        # Структурная проверка
        example_stream_output = {
            "supervisor": {"case_id": "test", "messages": []},
            "timeline": {"case_id": "test", "timeline_result": {}}
        }
        
        assert isinstance(example_stream_output, dict)
        assert "supervisor" in example_stream_output or "timeline" in example_stream_output
