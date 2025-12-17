"""Тесты для роутинга supervisor"""
import pytest
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.supervisor import route_to_agent


class TestSupervisorRouting:
    """Тесты для функции роутинга supervisor"""
    
    def test_route_independent_agents(self):
        """Тест роутинга независимых агентов"""
        # Timeline - независимый
        state: AnalysisState = {
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
        
        route = route_to_agent(state)
        assert route == "timeline"
        
        # Key facts - независимый
        state["analysis_types"] = ["key_facts"]
        route = route_to_agent(state)
        assert route == "key_facts"
        
        # Discrepancy - независимый
        state["analysis_types"] = ["discrepancy"]
        route = route_to_agent(state)
        assert route == "discrepancy"
    
    def test_route_dependent_agents_with_dependencies(self):
        """Тест роутинга зависимых агентов когда зависимости готовы"""
        # Risk требует discrepancy
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": {"discrepancies": [], "total": 0},  # Готово
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state)
        assert route == "risk"
        
        # Summary требует key_facts
        state["discrepancy_result"] = None
        state["key_facts_result"] = {"facts": {}, "result_id": "123"}  # Готово
        state["analysis_types"] = ["summary"]
        
        route = route_to_agent(state)
        assert route == "summary"
    
    def test_route_dependent_agents_without_dependencies(self):
        """Тест роутинга зависимых агентов когда зависимости не готовы"""
        # Risk без discrepancy - должен вернуться к supervisor
        state: AnalysisState = {
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
        
        route = route_to_agent(state)
        assert route == "supervisor"  # Ожидание зависимости
        
        # Summary без key_facts - должен вернуться к supervisor
        state["analysis_types"] = ["summary"]
        route = route_to_agent(state)
        assert route == "supervisor"
    
    def test_route_all_completed(self):
        """Тест роутинга когда все анализы завершены"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": []},
            "key_facts_result": {"facts": {}},
            "discrepancy_result": {"discrepancies": []},
            "risk_result": {"analysis": "test"},
            "summary_result": {"summary": "test"},
            "analysis_types": ["timeline", "key_facts", "discrepancy", "risk", "summary"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state)
        assert route == "end"
    
    def test_route_partial_completion(self):
        """Тест роутинга при частичном завершении"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": {"events": []},  # Завершено
            "key_facts_result": None,  # Не завершено
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state)
        # Должен направить к одному из незавершенных независимых агентов
        assert route in ["key_facts", "discrepancy"]
    
    def test_route_waiting_for_dependencies(self):
        """Тест ожидания зависимостей"""
        # Запрошен risk, но discrepancy еще не выполнен
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,  # Еще не готово
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        route = route_to_agent(state)
        assert route == "supervisor"  # Ожидание
        
        # Теперь discrepancy готово
        state["discrepancy_result"] = {"discrepancies": []}
        route = route_to_agent(state)
        assert route == "risk"  # Теперь можно выполнить
    
    def test_route_multiple_independent_parallel(self):
        """Тест роутинга нескольких независимых агентов для параллельного выполнения"""
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["timeline", "key_facts", "discrepancy"],
            "errors": [],
            "metadata": {}
        }
        
        # Первый вызов - должен направить к одному из независимых
        route1 = route_to_agent(state)
        assert route1 in ["timeline", "key_facts", "discrepancy"]
        
        # После завершения одного, должен направить к следующему
        state["timeline_result"] = {"events": []}
        route2 = route_to_agent(state)
        assert route2 in ["key_facts", "discrepancy"]
        
        # После завершения еще одного
        state["key_facts_result"] = {"facts": {}}
        route3 = route_to_agent(state)
        assert route3 == "discrepancy"
    
    def test_route_dependency_chain(self):
        """Тест роутинга цепочки зависимостей"""
        # Запрошены risk и summary, но нужны их зависимости
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,  # Нужно для summary
            "discrepancy_result": None,  # Нужно для risk
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk", "summary"],
            "errors": [],
            "metadata": {}
        }
        
        # Сначала должны выполниться зависимости
        route = route_to_agent(state)
        assert route in ["key_facts", "discrepancy"]  # Независимые агенты
        
        # После выполнения key_facts
        state["key_facts_result"] = {"facts": {}}
        route = route_to_agent(state)
        # Может направить к summary (если discrepancy еще не готово) или discrepancy
        assert route in ["summary", "discrepancy"]
        
        # После выполнения discrepancy
        state["discrepancy_result"] = {"discrepancies": []}
        route = route_to_agent(state)
        # Может направить к risk или summary
        assert route in ["risk", "summary"]
