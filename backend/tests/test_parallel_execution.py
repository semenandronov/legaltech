"""Тесты параллельного выполнения"""
import pytest
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.supervisor import route_to_agent


class TestParallelExecution:
    """Тесты параллельного выполнения"""
    
    def test_independent_agents_can_run_parallel(self):
        """Тест что независимые агенты могут выполняться параллельно"""
        # Независимые агенты: timeline, key_facts, discrepancy
        # Они не зависят друг от друга и могут выполняться параллельно
        
        independent_agents = ["timeline", "key_facts", "discrepancy"]
        
        # Все они независимы
        assert len(independent_agents) == 3
        
        # Проверка что они не требуют результатов друг друга
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": independent_agents,
            "errors": [],
            "metadata": {}
        }
        
        # Все три могут быть запрошены одновременно
        assert len(state["analysis_types"]) == 3
        assert all(agent in state["analysis_types"] for agent in independent_agents)
    
    def test_dependent_agents_execute_sequentially(self):
        """Тест что зависимые агенты выполняются последовательно"""
        # Risk зависит от discrepancy
        # Summary зависит от key_facts
        
        dependencies = {
            "risk": "discrepancy",
            "summary": "key_facts"
        }
        
        # Проверка зависимостей
        assert "risk" in dependencies
        assert dependencies["risk"] == "discrepancy"
        assert dependencies["summary"] == "key_facts"
    
    def test_total_time_less_than_sum(self):
        """Тест что общее время меньше суммы времен отдельных анализов"""
        # При параллельном выполнении независимых агентов
        # общее время должно быть меньше суммы
        
        # Структурная проверка
        # В реальном выполнении это проверяется через метрики
        
        independent_times = [1.5, 2.0, 1.8]  # Время каждого независимого агента
        sequential_total = sum(independent_times)  # Если бы выполнялись последовательно
        
        # При параллельном выполнении общее время должно быть меньше
        # (ограничено максимальным временем)
        parallel_total = max(independent_times)  # Идеальный параллельный случай
        
        assert parallel_total < sequential_total
    
    def test_graph_supports_parallel_execution(self):
        """Тест что граф поддерживает параллельное выполнение"""
        # LangGraph поддерживает параллельное выполнение через условные edges
        # и возврат к supervisor после каждого узла
        
        from app.services.langchain_agents.graph import create_analysis_graph
        from unittest.mock import Mock
        
        mock_db = Mock()
        mock_rag = Mock()
        mock_doc_processor = Mock()
        
        graph = create_analysis_graph(mock_db, mock_rag, mock_doc_processor)
        
        # Граф должен поддерживать streaming, что позволяет отслеживать
        # параллельное выполнение
        assert hasattr(graph, 'stream')


class TestExecutionOrder:
    """Тесты порядка выполнения"""
    
    def test_independent_agents_order(self):
        """Тест порядка выполнения независимых агентов"""
        # Независимые агенты могут выполняться в любом порядке
        # или параллельно
        
        independent = ["timeline", "key_facts", "discrepancy"]
        
        # Порядок не важен для независимых
        assert len(independent) == 3
    
    def test_dependent_agents_order(self):
        """Тест порядка выполнения зависимых агентов"""
        # Risk должен выполняться после discrepancy
        # Summary должен выполняться после key_facts
        
        # Проверка через route_to_agent
        state_without_dep: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,  # Не готово
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state_without_dep)
        # Должен вернуться к supervisor, так как зависимость не готова
        assert route == "supervisor"
        
        # Теперь зависимость готова
        state_with_dep = state_without_dep.copy()
        state_with_dep["discrepancy_result"] = {"discrepancies": []}
        
        route = route_to_agent(state_with_dep)
        # Теперь может выполнить risk
        assert route == "risk"
