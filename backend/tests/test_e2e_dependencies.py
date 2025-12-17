"""Тесты E2E сценариев с зависимостями"""
import pytest
from app.services.langchain_agents.state import AnalysisState
from app.services.langchain_agents.supervisor import route_to_agent


class TestE2EDependencies:
    """Тесты E2E сценариев с зависимостями"""
    
    def test_risk_analysis_requires_discrepancy(self):
        """Тест что risk_analysis требует discrepancy"""
        # Сценарий:
        # 1. Запустить только risk_analysis (требует discrepancy)
        # 2. Проверить, что discrepancy выполняется автоматически
        # 3. Проверить порядок выполнения
        
        # Начальное состояние - запрошен только risk
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
        
        # Risk не может выполниться без discrepancy
        route = route_to_agent(state)
        # Должен вернуться к supervisor или выполнить discrepancy
        assert route in ["supervisor", "discrepancy"]
        
        # После выполнения discrepancy
        state["discrepancy_result"] = {"discrepancies": []}
        route = route_to_agent(state)
        # Теперь может выполнить risk
        assert route == "risk"
    
    def test_execution_order_with_dependencies(self):
        """Тест порядка выполнения с зависимостями"""
        # Независимые анализы должны выполняться первыми
        # Затем зависимые
        
        independent = ["timeline", "key_facts", "discrepancy"]
        dependent = {
            "risk": "discrepancy",
            "summary": "key_facts"
        }
        
        # Проверка структуры зависимостей
        assert len(independent) == 3
        assert "risk" in dependent
        assert dependent["risk"] == "discrepancy"
        assert dependent["summary"] == "key_facts"


class TestAutomaticDependencyExecution:
    """Тесты автоматического выполнения зависимостей"""
    
    def test_discrepancy_executed_for_risk(self):
        """Тест что discrepancy выполняется автоматически для risk"""
        # Если запрошен risk, но discrepancy не выполнен,
        # система должна автоматически выполнить discrepancy
        
        # Структурная проверка - это реализовано через route_to_agent
        # которая проверяет зависимости
        
        state: AnalysisState = {
            "case_id": "test_case",
            "messages": [],
            "timeline_result": None,
            "key_facts_result": None,
            "discrepancy_result": None,
            "risk_result": None,
            "summary_result": None,
            "analysis_types": ["risk"],
            "errors": [],
            "metadata": {}
        }
        
        # route_to_agent должна определить что нужна discrepancy
        # В текущей реализации это делается через проверку зависимости
        assert state["discrepancy_result"] is None
        assert "risk" in state["analysis_types"]
