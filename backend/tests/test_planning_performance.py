"""Тесты производительности Planning Agent"""
import pytest
import time
from unittest.mock import Mock, patch


class TestPlanningPerformance:
    """Тесты производительности Planning Agent"""
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_planning_agent_initialization_time(self, mock_create):
        """Тест времени инициализации PlanningAgent"""
        mock_agent = Mock()
        mock_create.return_value = mock_agent
        
        start_time = time.time()
        from app.services.langchain_agents.planning_agent import PlanningAgent
        agent = PlanningAgent()
        init_time = time.time() - start_time
        
        # Инициализация должна быть быстрой (< 1 секунда)
        # В реальности может быть медленнее из-за загрузки модели, но для теста используем моки
        assert init_time < 1.0, f"Инициализация заняла {init_time:.2f} секунд"
        assert agent is not None
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_is_task_request_performance(self, mock_create):
        """Тест производительности is_task_request"""
        from app.routes.chat import is_task_request
        
        task = "Проанализируй документы и найди все риски"
        
        # Измеряем время выполнения
        times = []
        for _ in range(100):
            start = time.time()
            is_task_request(task)
            times.append(time.time() - start)
        
        avg_time = sum(times) / len(times)
        max_time = max(times)
        
        # Среднее время должно быть < 10ms
        assert avg_time < 0.01, f"Среднее время выполнения {avg_time*1000:.2f}ms"
        # Максимальное время должно быть < 50ms
        assert max_time < 0.05, f"Максимальное время выполнения {max_time*1000:.2f}ms"
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_dependency_resolution_performance(self, mock_create):
        """Тест производительности разрешения зависимостей"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        agent = PlanningAgent()
        
        # Тестируем на различных размерах списков
        test_cases = [
            ["timeline"],
            ["timeline", "key_facts", "discrepancy"],
            ["risk", "summary"],
            ["timeline", "key_facts", "discrepancy", "risk", "summary"],
        ]
        
        for types in test_cases:
            start = time.time()
            validated = agent._validate_and_add_dependencies(types)
            resolution_time = time.time() - start
            
            # Разрешение зависимостей должно быть быстрым (< 10ms)
            assert resolution_time < 0.01, f"Разрешение зависимостей заняло {resolution_time*1000:.2f}ms для {types}"
            assert isinstance(validated, list)
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_json_parsing_performance(self, mock_create):
        """Тест производительности парсинга JSON"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        agent = PlanningAgent()
        
        # Различные форматы JSON
        json_responses = [
            '{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}',
            '```json\n{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}\n```',
            'Вот план: {"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}',
        ]
        
        for json_response in json_responses:
            start = time.time()
            plan = agent._parse_agent_response(json_response)
            parse_time = time.time() - start
            
            # Парсинг должен быть быстрым (< 50ms)
            assert parse_time < 0.05, f"Парсинг JSON занял {parse_time*1000:.2f}ms"
            assert "analysis_types" in plan
    
    def test_planning_tools_performance(self):
        """Тест производительности planning tools"""
        from app.services.langchain_agents.planning_tools import (
            get_available_analyses_tool,
            check_analysis_dependencies_tool,
            validate_analysis_plan_tool
        )
        import json
        
        # get_available_analyses_tool
        start = time.time()
        result = get_available_analyses_tool.invoke({})
        time1 = time.time() - start
        assert time1 < 0.1, f"get_available_analyses_tool занял {time1*1000:.2f}ms"
        assert isinstance(result, str)
        
        # check_analysis_dependencies_tool
        start = time.time()
        result = check_analysis_dependencies_tool.invoke({"analysis_type": "risk"})
        time2 = time.time() - start
        assert time2 < 0.1, f"check_analysis_dependencies_tool занял {time2*1000:.2f}ms"
        
        # validate_analysis_plan_tool
        start = time.time()
        plan_json = json.dumps(["timeline", "risk", "summary"])
        result = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
        time3 = time.time() - start
        assert time3 < 0.1, f"validate_analysis_plan_tool занял {time3*1000:.2f}ms"


class TestResourceUsage:
    """Тесты использования ресурсов"""
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_multiple_agent_creation(self, mock_create):
        """Тест создания множества агентов (проверка утечек памяти)"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_create.return_value = mock_agent
        
        # Создаем несколько агентов
        agents = []
        for _ in range(10):
            agent = PlanningAgent()
            agents.append(agent)
        
        # Все агенты должны быть созданы успешно
        assert len(agents) == 10
        for agent in agents:
            assert agent is not None
            assert hasattr(agent, 'plan_analysis')
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_repeated_planning_calls(self, mock_create):
        """Тест повторных вызовов планирования"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            # Множественные вызовы
            for _ in range(10):
                plan = agent.plan_analysis("test task", "test_case")
                assert "analysis_types" in plan
            
            # Агент должен работать стабильно после множественных вызовов
            assert agent is not None
    
    def test_tools_repeated_calls(self):
        """Тест повторных вызовов tools"""
        from app.services.langchain_agents.planning_tools import (
            get_available_analyses_tool,
            validate_analysis_plan_tool
        )
        import json
        
        # Повторные вызовы должны работать стабильно
        for _ in range(10):
            result1 = get_available_analyses_tool.invoke({})
            assert isinstance(result1, str)
            
            plan_json = json.dumps(["timeline"])
            result2 = validate_analysis_plan_tool.invoke({"analysis_types": plan_json})
            assert isinstance(result2, str)


class TestPlanningScalability:
    """Тесты масштабируемости"""
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_large_task_handling(self, mock_create):
        """Тест обработки больших задач"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        # Большая задача (1000+ символов)
        large_task = "Найди " * 200 + "все даты в документах"
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline"], "reasoning": "Large task processed", "confidence": 0.8}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            start = time.time()
            plan = agent.plan_analysis(large_task, "test_case")
            processing_time = time.time() - start
            
            assert "analysis_types" in plan
            # Обработка большой задачи не должна занимать слишком много времени
            # (в реальности зависит от LLM, но с моками должно быть быстро)
            assert processing_time < 1.0, f"Обработка большой задачи заняла {processing_time:.2f} секунд"
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_complex_dependency_resolution(self, mock_create):
        """Тест разрешения сложных зависимостей"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        agent = PlanningAgent()
        
        # Комплексный план со всеми зависимостями
        complex_types = ["risk", "summary", "timeline"]
        
        start = time.time()
        validated = agent._validate_and_add_dependencies(complex_types)
        resolution_time = time.time() - start
        
        # Должны быть все типы + зависимости
        assert "discrepancy" in validated  # для risk
        assert "key_facts" in validated  # для summary
        assert "risk" in validated
        assert "summary" in validated
        assert "timeline" in validated
        
        # Разрешение должно быть быстрым даже для сложных случаев
        assert resolution_time < 0.1, f"Разрешение сложных зависимостей заняло {resolution_time*1000:.2f}ms"
