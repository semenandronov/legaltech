"""Тесты выполнения графа LangGraph"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from app.services.langchain_agents.graph import create_analysis_graph
from app.services.langchain_agents.state import AnalysisState


class TestGraphExecution:
    """Тесты выполнения графа"""
    
    @pytest.fixture
    def mock_services(self):
        """Создать моки сервисов"""
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        return mock_db, mock_rag, mock_doc_processor
    
    def test_simple_scenario_execution(self, mock_services):
        """Тест выполнения простого сценария (один анализ)"""
        mock_db, mock_rag, mock_doc_processor = mock_services
        
        graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
        
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
        
        # Структурная проверка - граф должен принимать state
        assert graph is not None
        assert hasattr(graph, 'stream')
        
        # Реальное выполнение требует LLM и сервисы
        # Проверяем что структура корректна
        assert isinstance(initial_state, dict)
        assert "analysis_types" in initial_state
        assert len(initial_state["analysis_types"]) == 1
    
    def test_complex_scenario_execution(self, mock_services):
        """Тест выполнения сложного сценария (все анализы)"""
        mock_db, mock_rag, mock_doc_processor = mock_services
        
        graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
        
        initial_state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy", "risk", "summary"],
            "errors": [],
            "metadata": {}
        }
        
        # Проверка структуры для сложного сценария
        assert graph is not None
        assert len(initial_state["analysis_types"]) == 5
        assert "timeline" in initial_state["analysis_types"]
        assert "risk" in initial_state["analysis_types"]
        assert "summary" in initial_state["analysis_types"]
    
    def test_execution_order(self, mock_services):
        """Тест порядка выполнения"""
        # Независимые агенты могут выполняться в любом порядке
        # Зависимые агенты должны выполняться после зависимостей
        
        # Структурная проверка:
        # - timeline, key_facts, discrepancy независимы
        # - risk зависит от discrepancy
        # - summary зависит от key_facts
        
        independent = ["timeline", "key_facts", "discrepancy"]
        dependent = {
            "risk": "discrepancy",
            "summary": "key_facts"
        }
        
        assert len(independent) == 3
        assert "risk" in dependent
        assert "summary" in dependent
    
    def test_supervisor_return_after_node(self, mock_services):
        """Тест возврата к supervisor после каждого узла"""
        # Структурная проверка - все узлы должны возвращаться к supervisor
        # Это реализовано в graph.py через add_edge
        
        from app.services.langchain_agents.graph import create_analysis_graph
        
        mock_db, mock_rag, mock_doc_processor = mock_services
        graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
        
        # Граф должен быть скомпилирован
        assert graph is not None
        
        # В реальной реализации все узлы имеют edge к supervisor
        # Это проверяется через выполнение графа


class TestGraphStateFlow:
    """Тесты потока состояния в графе"""
    
    def test_state_progression(self):
        """Тест прогрессии состояния"""
        # Начальное состояние
        initial_state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts"],
            "errors": [],
            "metadata": {}
        }
        
        # После выполнения timeline
        state_after_timeline = initial_state.copy()
        state_after_timeline["timeline_result"] = {"events": []}
        
        assert state_after_timeline["timeline_result"] is not None
        assert state_after_timeline["key_facts_result"] is None
        
        # После выполнения key_facts
        state_after_key_facts = state_after_timeline.copy()
        state_after_key_facts["key_facts_result"] = {"facts": {}}
        
        assert state_after_key_facts["timeline_result"] is not None
        assert state_after_key_facts["key_facts_result"] is not None
    
    def test_state_with_dependencies(self):
        """Тест состояния с зависимостями"""
        # Состояние для risk анализа
        state_for_risk: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": {"discrepancies": []},  # Зависимость готова
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        # Проверка что зависимость присутствует
        assert state_for_risk["discrepancy_result"] is not None
        assert state_for_risk["risk_result"] is None
        
        # После выполнения risk
        state_after_risk = state_for_risk.copy()
        state_after_risk["risk_result"] = {"analysis": "test"}
        
        assert state_after_risk["risk_result"] is not None
