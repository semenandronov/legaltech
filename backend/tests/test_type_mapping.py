"""Тесты для маппинга типов анализов между Planning Agent и API"""
import pytest
from unittest.mock import Mock, patch


class TestTypeMapping:
    """Тесты маппинга типов анализов"""
    
    def test_planning_to_api_mapping(self):
        """Тест маппинга Planning Agent типов -> API типы"""
        # Planning Agent использует: timeline, key_facts, discrepancy, risk, summary
        # API использует: timeline, key_facts, discrepancies, summary, risk_analysis
        
        planning_types = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        expected_api_types = ["timeline", "key_facts", "discrepancies", "risk_analysis", "summary"]
        
        # Симуляция маппинга как в chat endpoint
        api_types = []
        for at in planning_types:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        assert api_types == expected_api_types
    
    def test_api_to_agent_mapping(self):
        """Тест маппинга API типы -> Agent типы (в background task)"""
        api_types = ["timeline", "key_facts", "discrepancies", "risk_analysis", "summary"]
        expected_agent_types = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        
        # Симуляция маппинга как в background task
        agent_types = []
        for at in api_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        assert agent_types == expected_agent_types
    
    def test_mapping_preserves_order(self):
        """Тест что маппинг сохраняет порядок анализов"""
        planning_types = ["timeline", "discrepancy", "risk", "key_facts", "summary"]
        
        # Planning -> API
        api_types = []
        for at in planning_types:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        # Проверяем что порядок сохранен
        assert api_types.index("timeline") < api_types.index("discrepancies")
        assert api_types.index("discrepancies") < api_types.index("risk_analysis")
        assert api_types.index("key_facts") < api_types.index("summary")
        
        # API -> Agent
        agent_types = []
        for at in api_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        # Проверяем что порядок сохранен после обратного маппинга
        assert agent_types.index("timeline") < agent_types.index("discrepancy")
        assert agent_types.index("discrepancy") < agent_types.index("risk")
        assert agent_types.index("key_facts") < agent_types.index("summary")
    
    def test_mapping_preserves_dependencies(self):
        """Тест что маппинг сохраняет зависимости"""
        # Risk требует discrepancy, они должны идти в правильном порядке
        planning_types = ["risk"]  # discrepancy будет добавлен автоматически
        
        # Planning -> API (после добавления зависимостей)
        # В реальности зависимости добавляются перед маппингом
        planning_with_deps = ["discrepancy", "risk"]
        
        api_types = []
        for at in planning_with_deps:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        # Проверяем что порядок зависимостей сохранен
        assert api_types.index("discrepancies") < api_types.index("risk_analysis")
        
        # API -> Agent
        agent_types = []
        for at in api_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        # Проверяем что порядок сохранен
        assert agent_types.index("discrepancy") < agent_types.index("risk")
    
    def test_mapping_round_trip(self):
        """Тест что маппинг туда-обратно возвращает исходные значения"""
        planning_types = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        
        # Planning -> API
        api_types = []
        for at in planning_types:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        # API -> Agent (обратный маппинг)
        agent_types = []
        for at in api_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        # Должны получить исходные типы
        assert agent_types == planning_types
    
    def test_mapping_unknown_types(self):
        """Тест что неизвестные типы проходят через маппинг без изменений"""
        planning_types = ["timeline", "unknown_type", "key_facts"]
        
        # Planning -> API
        api_types = []
        for at in planning_types:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        # unknown_type должен пройти без изменений
        assert "unknown_type" in api_types
    
    def test_mapping_all_analysis_types(self):
        """Тест маппинга всех возможных типов анализов"""
        # Все типы из Planning Agent
        all_planning_types = ["timeline", "key_facts", "discrepancy", "risk", "summary"]
        
        # Mapping функция
        def map_planning_to_api(planning_type):
            if planning_type == "discrepancy":
                return "discrepancies"
            elif planning_type == "risk":
                return "risk_analysis"
            return planning_type
        
        # Проверяем все типы
        for planning_type in all_planning_types:
            api_type = map_planning_to_api(planning_type)
            assert api_type is not None
            assert isinstance(api_type, str)
            
            # Обратный маппинг
            def map_api_to_agent(api_type):
                if api_type == "discrepancies":
                    return "discrepancy"
                elif api_type == "risk_analysis":
                    return "risk"
                return api_type
            
            agent_type = map_api_to_agent(api_type)
            assert agent_type == planning_type


class TestTypeMappingInContext:
    """Тесты маппинга в контексте chat endpoint"""
    
    def test_chat_endpoint_mapping_logic(self):
        """Тест логики маппинга как в chat endpoint"""
        # Симуляция результата планирования
        plan = {
            "analysis_types": ["discrepancy", "risk"],
            "reasoning": "test",
            "confidence": 0.9
        }
        
        analysis_types = plan["analysis_types"]
        
        # Маппинг Planning -> API (как в chat endpoint)
        api_analysis_types = []
        for at in analysis_types:
            if at == "discrepancy":
                api_analysis_types.append("discrepancies")
            elif at == "risk":
                api_analysis_types.append("risk_analysis")
            else:
                api_analysis_types.append(at)
        
        assert api_analysis_types == ["discrepancies", "risk_analysis"]
    
    def test_background_task_mapping_logic(self):
        """Тест логики маппинга в background task"""
        # API типы из metadata
        api_analysis_types = ["discrepancies", "risk_analysis"]
        
        # Маппинг API -> Agent (как в background task)
        agent_types = []
        for at in api_analysis_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        assert agent_types == ["discrepancy", "risk"]
    
    def test_full_flow_mapping(self):
        """Тест полного потока маппинга от планирования до выполнения"""
        # 1. Planning Agent создает план
        planning_result = ["discrepancy", "risk"]
        
        # 2. Chat endpoint маппит в API формат
        api_types = []
        for at in planning_result:
            if at == "discrepancy":
                api_types.append("discrepancies")
            elif at == "risk":
                api_types.append("risk_analysis")
            else:
                api_types.append(at)
        
        # 3. Background task маппит обратно в Agent формат
        agent_types = []
        for at in api_types:
            if at == "discrepancies":
                agent_types.append("discrepancy")
            elif at == "risk_analysis":
                agent_types.append("risk")
            else:
                agent_types.append(at)
        
        # 4. Проверяем что получили исходные типы
        assert agent_types == planning_result
        
        # 5. Проверяем что порядок сохранен (discrepancy перед risk)
        assert agent_types.index("discrepancy") < agent_types.index("risk")
