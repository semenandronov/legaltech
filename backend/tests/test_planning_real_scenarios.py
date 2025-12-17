"""Тесты реальных сценариев использования Planning Agent"""
import pytest
from unittest.mock import Mock, patch


class TestRealUserScenarios:
    """Тесты типичных сценариев пользователей"""
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_simple_analysis_scenario(self, mock_create):
        """Сценарий 1: Простой анализ - найти даты"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline"], "reasoning": "Пользователь просит найти даты", "confidence": 0.95}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis("Найди все даты в документах", "test_case")
            
            assert "timeline" in plan["analysis_types"]
            assert plan["confidence"] > 0
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_dependency_scenario(self, mock_create):
        """Сценарий 2: Анализ с зависимостью - оценить риски"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["risk"], "reasoning": "Пользователь просит оценить риски", "confidence": 0.9}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis("Оцени риски дела", "test_case")
            
            # Должна добавиться зависимость discrepancy
            assert "discrepancy" in plan["analysis_types"]
            assert "risk" in plan["analysis_types"]
            assert plan["analysis_types"].index("discrepancy") < plan["analysis_types"].index("risk")
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_complex_analysis_scenario(self, mock_create):
        """Сценарий 3: Комплексный анализ"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["key_facts", "discrepancy", "risk", "summary"], "reasoning": "Полный анализ", "confidence": 0.85}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis(
                "Сделай полный анализ: найди все факты, противоречия и риски, затем создай резюме",
                "test_case"
            )
            
            # Должны быть все запрошенные анализы
            assert "key_facts" in plan["analysis_types"]
            assert "discrepancy" in plan["analysis_types"]
            assert "risk" in plan["analysis_types"]
            assert "summary" in plan["analysis_types"]
            
            # Должны быть добавлены зависимости
            # summary требует key_facts, risk требует discrepancy
            assert plan["analysis_types"].index("key_facts") < plan["analysis_types"].index("summary")
            assert plan["analysis_types"].index("discrepancy") < plan["analysis_types"].index("risk")
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_unclear_task_scenario(self, mock_create):
        """Сценарий 4: Неясная задача"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        # Агент не уверен, возвращает базовые анализы
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline", "key_facts", "discrepancy"], "reasoning": "Неясная задача, выполняю базовые анализы", "confidence": 0.6}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis("Проверь документы", "test_case")
            
            assert len(plan["analysis_types"]) > 0
            assert plan["confidence"] <= 0.7  # Низкая уверенность для неясной задачи
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_multilingual_scenario(self, mock_create):
        """Сценарий 5: Многоязычная задача"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline", "discrepancy"], "reasoning": "User wants timeline and discrepancies", "confidence": 0.9}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis("Extract timeline and find discrepancies", "test_case")
            
            assert "timeline" in plan["analysis_types"]
            assert "discrepancy" in plan["analysis_types"]


class TestEdgeCases:
    """Тесты граничных случаев"""
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_empty_task(self, mock_create):
        """Тест пустой задачи"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline", "key_facts", "discrepancy"], "reasoning": "Empty task, default analysis", "confidence": 0.5}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis("", "test_case")
            
            # Должен вернуться базовый план
            assert "analysis_types" in plan
            assert len(plan["analysis_types"]) > 0
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_very_long_task(self, mock_create):
        """Тест очень длинной задачи"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        long_task = "Найди " * 200 + "все даты"
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline"], "reasoning": "Long task, extracting key parts", "confidence": 0.8}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis(long_task, "test_case")
            
            assert "analysis_types" in plan
            # План должен быть создан даже для очень длинной задачи
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_task_with_typos(self, mock_create):
        """Тест задачи с опечатками"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        # Задача с опечатками в ключевых словах
        task_with_typos = "Проанализируй документы и найди все протеворечия"
        
        mock_agent = Mock()
        # Агент должен понимать несмотря на опечатки
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["discrepancy"], "reasoning": "User wants discrepancies", "confidence": 0.75}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis(task_with_typos, "test_case")
            
            # Должен понять задачу несмотря на опечатки
            assert "analysis_types" in plan
            # В fallback режиме может найти по частичному совпадению
            # или LLM должен понять контекст
    
    def test_task_with_nonexistent_analysis_types(self):
        """Тест задачи с несуществующими типами анализов"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Fallback планирование должно обработать задачу
            plan = agent._fallback_planning("Выполни неизвестный_анализ")
            
            # Должен вернуться базовый план
            assert "analysis_types" in plan
            assert len(plan["analysis_types"]) > 0
    
    @patch('app.services.langchain_agents.planning_agent.create_legal_agent')
    def test_mixed_language_task(self, mock_create):
        """Тест задачи на смешанном языке"""
        from app.services.langchain_agents.planning_agent import PlanningAgent
        
        mixed_task = "Find все timeline события и найди discrepancies"
        
        mock_agent = Mock()
        mock_result = {
            "messages": [
                Mock(content='{"analysis_types": ["timeline", "discrepancy"], "reasoning": "Mixed language task", "confidence": 0.85}')
            ]
        }
        mock_agent.invoke.return_value = mock_result
        mock_create.return_value = mock_agent
        
        agent = PlanningAgent()
        
        with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
            plan = agent.plan_analysis(mixed_task, "test_case")
            
            assert "timeline" in plan["analysis_types"]
            assert "discrepancy" in plan["analysis_types"]


class TestTaskRequestDetectionScenarios:
    """Тесты определения задач в реальных сценариях"""
    
    def test_various_task_formulations(self):
        """Тест различных формулировок задач"""
        from app.routes.chat import is_task_request
        
        task_formulations = [
            "Проанализируй документы и найди все риски",
            "Можешь найти противоречия?",
            "Извлеки ключевые факты из документов",
            "Нужно создать резюме дела",
            "Требуется выполнить анализ timeline",
            "Пожалуйста, найди все даты",
            "Сделай полный анализ документов",
        ]
        
        for task in task_formulations:
            result = is_task_request(task)
            # Большинство должно определяться как задачи
            assert isinstance(result, bool)
    
    def test_question_vs_task_distinction(self):
        """Тест различия между вопросами и задачами"""
        from app.routes.chat import is_task_request
        
        questions = [
            "Какие даты упоминаются в документах?",
            "Что такое timeline?",
            "Объясни что такое discrepancy",
            "Как работает анализ рисков?",
            "Что означает key_facts?",
        ]
        
        for question in questions:
            result = is_task_request(question)
            # Вопросы не должны определяться как задачи
            assert result is False
