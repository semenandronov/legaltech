"""End-to-End тесты для Planning Agent"""
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestPlanningE2E:
    """E2E тесты полного цикла: задача -> план -> выполнение"""
    
    @patch('app.services.analysis_service.AnalysisService')
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_full_cycle_task_to_execution(self, mock_create_agent, mock_analysis_service):
        """Тест полного цикла от задачи до выполнения анализа"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
        
        # 1. Planning Agent создает план
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["risk"], "reasoning": "User wants risk analysis", "confidence": 0.9}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create_agent.return_value = mock_agent
        
        planning_agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = planning_agent.plan_analysis("Проанализируй риски", "test_case")
            
            # 2. Проверяем что план создан
            assert "analysis_types" in plan
            assert "risk" in plan["analysis_types"]
            
            # 3. Проверяем что зависимости добавлены
            assert "discrepancy" in plan["analysis_types"]
            assert plan["analysis_types"].index("discrepancy") < plan["analysis_types"].index("risk")
            
            # 4. Симуляция маппинга Planning -> API
            api_types = []
            for at in plan["analysis_types"]:
                if at == "discrepancy":
                    api_types.append("discrepancies")
                elif at == "risk":
                    api_types.append("risk_analysis")
                else:
                    api_types.append(at)
            
            assert "discrepancies" in api_types
            assert "risk_analysis" in api_types
            
            # 5. Симуляция маппинга API -> Agent для выполнения
            agent_types = []
            for at in api_types:
                if at == "discrepancies":
                    agent_types.append("discrepancy")
                elif at == "risk_analysis":
                    agent_types.append("risk")
                else:
                    agent_types.append(at)
            
            assert agent_types == ["discrepancy", "risk"]
            assert agent_types.index("discrepancy") < agent_types.index("risk")
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_e2e_with_multiple_analyses(self, mock_create_agent):
        """Тест E2E с несколькими анализами"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline", "risk", "summary"], "reasoning": "Full analysis", "confidence": 0.85}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create_agent.return_value = mock_agent
        
        planning_agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = planning_agent.plan_analysis("Сделай полный анализ", "test_case")
            
            # Проверяем что все анализы присутствуют
            assert "timeline" in plan["analysis_types"]
            assert "risk" in plan["analysis_types"]
            assert "summary" in plan["analysis_types"]
            
            # Проверяем зависимости
            assert "discrepancy" in plan["analysis_types"]  # для risk
            assert "key_facts" in plan["analysis_types"]  # для summary
            
            # Проверяем порядок зависимостей
            types = plan["analysis_types"]
            assert types.index("discrepancy") < types.index("risk")
            assert types.index("key_facts") < types.index("summary")


class TestPlanningWithRealComponents:
    """Тесты интеграции Planning Agent с реальными компонентами"""
    
    def test_planning_agent_with_available_analyses(self):
        """Тест что Planning Agent знает о всех доступных анализах"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES
        
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Проверяем что можем валидировать все типы
            for analysis_type in AVAILABLE_ANALYSES.keys():
                validated = agent._validate_and_add_dependencies([analysis_type])
                assert len(validated) > 0
                assert analysis_type in validated
    
    def test_planning_tools_integration(self):
        """Тест интеграции Planning Tools с Planning Agent"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        from app.services.langchain_agents.planning_tools import get_planning_tools, AVAILABLE_ANALYSES
        
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Проверяем что tools доступны
            tools = get_planning_tools()
            assert len(tools) > 0
            
            # Проверяем что agent может использовать информацию из AVAILABLE_ANALYSES
            for analysis_type in AVAILABLE_ANALYSES.keys():
                validated = agent._validate_and_add_dependencies([analysis_type])
                assert analysis_type in validated
    
    def test_planning_agent_prompt_integration(self):
        """Тест интеграции Planning Agent с промптами"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        from app.services.langchain_agents.prompts import get_agent_prompt, PLANNING_AGENT_PROMPT
        
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            # Проверяем что промпт загружается
            prompt = get_agent_prompt("planning")
            assert prompt == PLANNING_AGENT_PROMPT
            assert len(prompt) > 0
            
            agent = PlanningAgent()
            assert agent is not None


class TestPlanningWithChatEndpoint:
    """Тесты интеграции Planning Agent с chat endpoint"""
    
    def test_task_detection_integration(self):
        """Тест интеграции определения задач"""
        from app.routes.chat import is_task_request
        from app.services.langchain_agents import PlanningAgent
        
        # Проверяем что компоненты работают вместе
        assert callable(is_task_request)
        assert PlanningAgent is not None
        
        # Тестируем определение задачи
        task = "Проанализируй риски"
        is_task = is_task_request(task)
        assert is_task is True
    
    def test_planning_to_chat_flow(self):
        """Тест потока от планирования до chat endpoint"""
        from app.routes.chat import is_task_request
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        # Симуляция потока
        user_input = "Проанализируй риски"
        
        # 1. Определение задачи
        is_task = is_task_request(user_input)
        assert is_task is True
        
        # 2. Создание плана (с моками)
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_result = {
                "messages": [
                    Mock(content='{"analysis_types": ["risk"], "reasoning": "test", "confidence": 0.9}')
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            planning_agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = planning_agent.plan_analysis(user_input, "test_case")
                
                # 3. Проверяем что план создан
                assert "analysis_types" in plan
                assert "risk" in plan["analysis_types"]
                
                # 4. Проверяем маппинг для API
                api_types = []
                for at in plan["analysis_types"]:
                    if at == "discrepancy":
                        api_types.append("discrepancies")
                    elif at == "risk":
                        api_types.append("risk_analysis")
                    else:
                        api_types.append(at)
                
                assert "discrepancies" in api_types or "risk_analysis" in api_types


class TestPlanningDependencyFlow:
    """Тесты потока зависимостей в E2E сценарии"""
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_dependency_resolution_e2e(self, mock_create_agent):
        """Тест разрешения зависимостей в E2E сценарии"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        # Пользователь запрашивает только risk
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["risk"], "reasoning": "User wants risk", "confidence": 0.9}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create_agent.return_value = mock_agent
        
        planning_agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = planning_agent.plan_analysis("Проанализируй риски", "test_case")
            
            # Должна добавиться зависимость discrepancy
            assert "discrepancy" in plan["analysis_types"]
            assert "risk" in plan["analysis_types"]
            
            # Порядок должен быть правильным для выполнения
            types = plan["analysis_types"]
            dep_idx = types.index("discrepancy")
            risk_idx = types.index("risk")
            
            assert dep_idx < risk_idx, "discrepancy должен выполняться перед risk"
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_multiple_dependencies_e2e(self, mock_create_agent):
        """Тест множественных зависимостей в E2E"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        # Пользователь запрашивает risk и summary
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["risk", "summary"], "reasoning": "User wants both", "confidence": 0.85}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create_agent.return_value = mock_agent
        
        planning_agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = planning_agent.plan_analysis("Проанализируй риски и создай резюме", "test_case")
            
            # Должны быть все анализы + зависимости
            assert "discrepancy" in plan["analysis_types"]  # для risk
            assert "key_facts" in plan["analysis_types"]  # для summary
            assert "risk" in plan["analysis_types"]
            assert "summary" in plan["analysis_types"]
            
            # Порядок должен быть правильным
            types = plan["analysis_types"]
            assert types.index("discrepancy") < types.index("risk")
            assert types.index("key_facts") < types.index("summary")
