"""Тесты для Planning Agent"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from app.services.langchain_agents.planning_agent import PlanningAgent
from app.services.langchain_agents.planning_tools import AVAILABLE_ANALYSES


class TestPlanningAgent:
    """Тесты для Planning Agent"""
    
    def test_planning_agent_initialization(self):
        """Тест инициализации Planning Agent"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            assert agent is not None
            assert hasattr(agent, 'llm')
            assert hasattr(agent, 'tools')
            assert hasattr(agent, 'agent')
            assert hasattr(agent, 'plan_analysis')
    
    def test_validate_and_add_dependencies_simple(self):
        """Тест валидации и добавления зависимостей для простого случая"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Независимые анализы не должны изменяться
            types = ["timeline", "key_facts", "discrepancy"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert set(validated) == set(types)
            assert len(validated) == 3
    
    def test_validate_and_add_dependencies_with_dependencies(self):
        """Тест добавления зависимостей"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Risk требует discrepancy
            types = ["risk"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert "discrepancy" in validated
            assert "risk" in validated
            assert validated.index("discrepancy") < validated.index("risk")
            
            # Summary требует key_facts
            types = ["summary"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert "key_facts" in validated
            assert "summary" in validated
            assert validated.index("key_facts") < validated.index("summary")
    
    def test_validate_and_add_dependencies_complex(self):
        """Тест сложного случая с множественными зависимостями"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Комплексный план
            types = ["timeline", "risk", "summary"]
            validated = agent._validate_and_add_dependencies(types)
            
            # Должны быть все запрошенные
            assert "timeline" in validated
            assert "risk" in validated
            assert "summary" in validated
            
            # Должны быть зависимости
            assert "discrepancy" in validated  # для risk
            assert "key_facts" in validated  # для summary
            
            # Зависимости должны идти перед зависимыми анализами
            assert validated.index("discrepancy") < validated.index("risk")
            assert validated.index("key_facts") < validated.index("summary")
    
    def test_fallback_planning(self):
        """Тест fallback планирования"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Тест с ключевым словом "риски"
            plan = agent._fallback_planning("Проанализируй риски")
            
            assert "analysis_types" in plan
            assert "reasoning" in plan
            assert "confidence" in plan
            assert "risk" in plan["analysis_types"] or "discrepancy" in plan["analysis_types"]
    
    def test_parse_agent_response_json(self):
        """Тест парсинга JSON ответа агента"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Чистый JSON
            response = '{"analysis_types": ["timeline", "key_facts"], "reasoning": "test", "confidence": 0.9}'
            plan = agent._parse_agent_response(response)
            
            assert plan["analysis_types"] == ["timeline", "key_facts"]
            assert plan["reasoning"] == "test"
            assert plan["confidence"] == 0.9
    
    def test_parse_agent_response_markdown(self):
        """Тест парсинга JSON из markdown блока"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # JSON в markdown
            response = '```json\n{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.8}\n```'
            plan = agent._parse_agent_response(response)
            
            assert "analysis_types" in plan
            assert plan["analysis_types"] == ["timeline"]
    
    def test_parse_agent_response_text_extraction(self):
        """Тест извлечения плана из текста (fallback)"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Текст с упоминанием timeline
            response = "Нужно выполнить timeline анализ для извлечения дат"
            plan = agent._parse_agent_response(response)
            
            # Должен найти timeline через text extraction
            assert "analysis_types" in plan
            assert isinstance(plan["analysis_types"], list)
    
    def test_plan_analysis_structure(self):
        """Тест структуры результата plan_analysis"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_result = {
                "messages": [
                    Mock(content='{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}')
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            # Мокаем сообщение
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("Найди все даты", "test_case")
                
                assert "analysis_types" in plan
                assert "reasoning" in plan
                assert "confidence" in plan
                assert isinstance(plan["analysis_types"], list)
                assert isinstance(plan["reasoning"], str)
                assert isinstance(plan["confidence"], (int, float))
    
    def test_plan_analysis_error_handling(self):
        """Тест обработки ошибок в plan_analysis"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_agent.invoke.side_effect = Exception("Test error")
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            # При ошибке должен вернуться fallback план
            plan = agent.plan_analysis("test task", "test_case")
            
            assert "analysis_types" in plan
            assert "reasoning" in plan
            assert "confidence" in plan
    
    def test_plan_analysis_with_dependencies_auto_added(self):
        """Тест что зависимости автоматически добавляются"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            # Агент возвращает только risk, без discrepancy
            mock_result = {
                "messages": [
                    Mock(content='{"analysis_types": ["risk"], "reasoning": "test", "confidence": 0.9}')
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("Проанализируй риски", "test_case")
                
                # Должна добавиться dependency discrepancy
                assert "discrepancy" in plan["analysis_types"]
                assert "risk" in plan["analysis_types"]
                assert plan["analysis_types"].index("discrepancy") < plan["analysis_types"].index("risk")


    def test_planning_agent_llm_params(self):
        """Тест что LLM инициализируется с правильными параметрами"""
        with patch('app.services.langchain_agents.planning_agent.ChatOpenAI') as mock_llm:
            with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
                agent = PlanningAgent()
                
                # Проверяем что ChatOpenAI был вызван с правильными параметрами
                mock_llm.assert_called_once()
                call_kwargs = mock_llm.call_args[1]
                assert call_kwargs.get("temperature") == 0.1
                assert call_kwargs.get("max_tokens") == 500
    
    def test_planning_agent_prompt_loading(self):
        """Тест что prompt загружается правильно"""
        with patch('app.services.langchain_agents.planning_agent.get_agent_prompt') as mock_prompt:
            mock_prompt.return_value = "test prompt"
            with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
                agent = PlanningAgent()
                
                # Проверяем что get_agent_prompt был вызван с "planning"
                mock_prompt.assert_called_once_with("planning")
                
                # Проверяем что create_legal_agent был вызван с prompt
                mock_create.assert_called_once()
                call_args = mock_create.call_args
                assert call_args[1]["system_prompt"] == "test prompt"
    
    def test_parse_agent_response_plain_code_block(self):
        """Тест парсинга JSON из обычного code block"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # JSON в обычном code block без json метки
            response = '```\n{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.8}\n```'
            plan = agent._parse_agent_response(response)
            
            assert "analysis_types" in plan
            assert plan["analysis_types"] == ["timeline"]
    
    def test_parse_agent_response_multiline_json(self):
        """Тест парсинга многострочного JSON"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            multiline_json = '''{
                "analysis_types": ["timeline", "key_facts"],
                "reasoning": "Test reasoning",
                "confidence": 0.85
            }'''
            plan = agent._parse_agent_response(multiline_json)
            
            assert plan["analysis_types"] == ["timeline", "key_facts"]
            assert plan["reasoning"] == "Test reasoning"
            assert plan["confidence"] == 0.85
    
    def test_parse_agent_response_with_text_before_after(self):
        """Тест парсинга JSON с текстом до и после"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            response = 'Вот план анализа:\n{"analysis_types": ["discrepancy"], "confidence": 0.9}\nЭто финальный план.'
            plan = agent._parse_agent_response(response)
            
            assert "analysis_types" in plan
            assert "discrepancy" in plan["analysis_types"]
    
    def test_extract_plan_from_text_keyword_matching(self):
        """Тест извлечения плана по ключевым словам"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Текст с упоминанием нескольких типов
            response = "Нужно выполнить timeline анализ и найти discrepancy в документах"
            plan = agent._extract_plan_from_text(response)
            
            assert "analysis_types" in plan
            assert "timeline" in plan["analysis_types"]
            assert "discrepancy" in plan["analysis_types"]
    
    def test_extract_plan_from_text_fallback_default(self):
        """Тест что fallback возвращает базовый план при отсутствии совпадений"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Текст без упоминания типов анализов
            response = "Нужно проверить документы"
            plan = agent._extract_plan_from_text(response)
            
            assert "analysis_types" in plan
            assert len(plan["analysis_types"]) > 0
            # Должен вернуть базовый план (timeline, key_facts, discrepancy)
            assert plan["confidence"] == 0.6
    
    def test_fallback_planning_keyword_detection(self):
        """Тест что fallback планирование находит анализы по ключевым словам"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Тест с разными ключевыми словами
            test_cases = [
                ("Найди все даты", ["timeline"]),
                ("Извлеки ключевые факты", ["key_facts"]),
                ("Найди противоречия", ["discrepancy"]),
                ("Проанализируй риски", ["risk", "discrepancy"]),  # risk требует discrepancy
            ]
            
            for task, expected_types in test_cases:
                plan = agent._fallback_planning(task)
                assert "analysis_types" in plan
                for expected_type in expected_types:
                    assert expected_type in plan["analysis_types"]
    
    def test_fallback_planning_adds_dependencies(self):
        """Тест что fallback планирование добавляет зависимости"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Задача только про риски
            plan = agent._fallback_planning("Проанализируй риски")
            
            # Должна добавиться dependency discrepancy
            assert "discrepancy" in plan["analysis_types"]
            assert "risk" in plan["analysis_types"]
            assert plan["analysis_types"].index("discrepancy") < plan["analysis_types"].index("risk")
    
    def test_fallback_planning_confidence(self):
        """Тест что fallback планирование имеет правильный confidence"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            plan = agent._fallback_planning("test task")
            assert plan["confidence"] == 0.6
    
    def test_validate_and_add_dependencies_duplicates(self):
        """Тест что validate_and_add_dependencies не добавляет дубликаты"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Если discrepancy уже есть, не должен добавиться второй раз
            types = ["discrepancy", "risk"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert validated.count("discrepancy") == 1
            assert validated.count("risk") == 1
    
    def test_validate_and_add_dependencies_unknown_type(self):
        """Тест что неизвестные типы пропускаются"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            types = ["timeline", "unknown_type", "key_facts"]
            validated = agent._validate_and_add_dependencies(types)
            
            assert "unknown_type" not in validated
            assert "timeline" in validated
            assert "key_facts" in validated
    
    def test_plan_analysis_default_reasoning_confidence(self):
        """Тест что plan_analysis добавляет reasoning и confidence если их нет"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            # Агент возвращает JSON без reasoning и confidence
            mock_result = {
                "messages": [
                    Mock(content='{"analysis_types": ["timeline"]}')
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage'):
                plan = agent.plan_analysis("test", "test_case")
                
                assert "reasoning" in plan
                assert "confidence" in plan
                assert plan["confidence"] == 0.8  # default value
                assert isinstance(plan["reasoning"], str)
    
    def test_plan_analysis_includes_documents(self):
        """Тест что available_documents включаются в сообщение"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent') as mock_create:
            mock_agent = Mock()
            mock_result = {
                "messages": [
                    Mock(content='{"analysis_types": ["timeline"], "reasoning": "test", "confidence": 0.9}')
                ]
            }
            mock_agent.invoke.return_value = mock_result
            mock_create.return_value = mock_agent
            
            agent = PlanningAgent()
            
            with patch('app.services.langchain_agents.planning_agent.HumanMessage') as mock_msg:
                documents = ["doc1.pdf", "doc2.pdf"]
                agent.plan_analysis("test", "test_case", available_documents=documents)
                
                # Проверяем что HumanMessage был создан с правильным content
                mock_msg.assert_called_once()
                call_content = mock_msg.call_args[0][0]
                assert "doc1.pdf" in call_content
                assert "doc2.pdf" in call_content


class TestPlanningAgentIntegration:
    """Интеграционные тесты Planning Agent"""
    
    def test_planning_agent_with_available_analyses(self):
        """Тест что Planning Agent знает о всех доступных анализах"""
        with patch('app.services.langchain_agents.planning_agent.create_legal_agent'):
            agent = PlanningAgent()
            
            # Проверяем что можем валидировать все типы
            for analysis_type in AVAILABLE_ANALYSES.keys():
                validated = agent._validate_and_add_dependencies([analysis_type])
                assert len(validated) > 0
                assert analysis_type in validated
